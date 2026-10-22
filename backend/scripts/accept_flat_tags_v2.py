"""Run a labeled acceptance subject through real APIs against a migrated MySQL.

Creates samples only in the explicit flat-tags-v2 acceptance subject; existing
questions and labels are untouched. Exports and an ID-only report are retained.
"""
import asyncio
import io
import json
from pathlib import Path
import sys
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.core.config import get_db_url
from app.core.security import create_access_token
from app.models import Subject, User, Tag
from scripts.seed_flat_tags_v2 import seed_subject


async def acceptance(url, output):
    from app.api import deps
    from app.main import app
    engine = create_async_engine(url, hide_parameters=True)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    async def get_db():
        async with maker() as db:
            yield db
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[deps.get_db] = get_db
    try:
        async with maker() as db:
            admin = (await db.execute(select(User).where(User.is_superuser.is_(True), User.is_active.is_(True)).order_by(User.id))).scalars().first()
            if not admin:
                raise RuntimeError("Acceptance requires an existing active administrator")
            subject = (await db.execute(select(Subject).where(Subject.slug == 'flat-tags-v2-acceptance'))).scalar_one_or_none()
            if subject:
                raise RuntimeError("Acceptance subject already exists; use its saved report rather than duplicating samples")
            subject = Subject(name='扁平标签 v2 验收样本（独立）', slug='flat-tags-v2-acceptance', required_review_count=1)
            db.add(subject); await db.flush()
            template = await seed_subject(db, subject); await db.commit()
            sid, tid = subject.id, template.id
            parts = template.parts_json
            tag_names = {tag.id: tag.name for tag in (await db.execute(select(Tag).where(Tag.subject_id == sid))).scalars()}
            headers = {'Authorization': 'Bearer ' + create_access_token(subject=admin.id)}
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://acceptance', headers=headers, timeout=120) as client:
            async def call(method, path, body=None):
                r = await client.request(method, '/api/v1' + path, json=body)
                if r.status_code != 200:
                    raise RuntimeError(f"Acceptance {method} {path}: {r.status_code} {r.text[:1000]}")
                return r.json()
            blocks = []
            for part in parts:
                for rule in part['sections']:
                    qt = rule['q_type']
                    name = {'single_choice':'单选题','multiple_choice':'多选题','free_response':'案例分析'}[qt]
                    for i in range(rule['count'] * 2 + 1):
                        options = '\n【选项】A.正确的处理方式\nB.需要复核的处理方式' if qt != 'free_response' else ''
                        answer = 'AB' if qt == 'multiple_choice' else 'A' if qt == 'single_choice' else '根据材料说明依据和处置步骤。'
                        blocks.append(f"【题目】验收样本 {rule['key']}-{i+1}，请作答。\n【题型】{name}{options}\n【答案】{answer}\n【标签】" + '，'.join(tag_names[t] for t in rule['tag_filter']['tag_ids']))
            markdown = '\n\n'.join(blocks)
            (output / 'acceptance-import.md').write_text(markdown, encoding='utf-8')
            extracted = await call('POST', '/upload/markdown-text', {'content':markdown,'filename':'flat-tags-v2-acceptance.md','mode':'extract','method':'structured','subject_id':sid})
            assert len(extracted['questions']) == len(blocks)
            fields = {'content','q_type','options','answer','thinking','analysis','summary','difficulty','tag_ids','knowledge_point_ids','subject_id','ai_suggested_tags'}
            questions = [{**{k:v for k,v in q.items() if k in fields},'status':'draft','source':'flat-tags-v2 acceptance'} for q in extracted['questions']]
            assert all(q['tag_ids'] and q['q_type'] in ('single_choice','multiple_choice','free_response') for q in questions)
            saved = await call('POST','/questions/batch',{'questions':questions})
            ids = [q['id'] for q in saved]
            await call('POST','/questions/batch-confirm',{'question_ids':ids,'action':'approve'})
            for qid in ids:
                reviewed = await call('POST',f'/questions/{qid}/review',{'action':'approve','comment':'扁平标签 v2 独立样本验收'})
                assert reviewed['status'] == 'published'
            report = await call('POST',f'/paper-templates/{tid}/preflight',{'n_sets':2,'cross_set_dedup':True})
            assert report['feasible'] and report['required_slots'] == 50
            batch = await call('POST','/exam-papers/generate',{'template_id':tid,'n_sets':2,'cross_set_dedup':True,'title':'扁平标签 v2 验收卷'})
            used = [i['question_id'] for p in batch['papers'] for i in p['items']]
            assert len(used) == len(set(used)) == 50
            assert all(p['actual_total_score'] == 100 for p in batch['papers'])
            left, right = [p['items'][0] for p in batch['papers']]
            target_tags = {t['id'] for t in left['tag_snapshot_json']}
            spare = next(q for q in saved if q['id'] not in used and q['q_type'] == left['q_type']
                         and {t['id'] for t in q['tags']} == target_tags)
            simultaneous = await asyncio.gather(*[
                client.post(f"/api/v1/exam-papers/{p['id']}/items/{item['id']}/replace",
                            json={'mode':'manual','question_id':spare['id']})
                for p,item in zip(batch['papers'],(left,right))
            ])
            assert sorted(r.status_code for r in simultaneous) == [200,400], [r.text[:300] for r in simultaneous]
            batch = await call('GET',f"/exam-papers/batches/{batch['id']}")
            used = [i['question_id'] for p in batch['papers'] for i in p['items']]
            assert len(used) == len(set(used)) == 50
            p = batch['papers'][0]; item = p['items'][0]
            changed = await call('PATCH',f"/exam-papers/{p['id']}/items/{item['id']}",{'score':item['score']+0.1})
            assert changed['actual_total_score'] == 100.1
            await call('PATCH',f"/exam-papers/{p['id']}/items/{item['id']}",{'score':item['score']})
            changed = await call('POST',f"/exam-papers/{p['id']}/items/{item['id']}/replace",{'mode':'random_same_type'})
            assert changed['items'][0]['question_id'] != item['question_id']
            changed = await call('POST',f"/exam-papers/{p['id']}/items/{item['id']}/replace",{'mode':'manual','question_id':item['question_id']})
            assert changed['items'][0]['section_key'] == item['section_key']
            artifacts = []
            for p in batch['papers']:
                final = await call('POST',f"/exam-papers/{p['id']}/finalize")
                assert final['status'] == 'final'
                for mode in ('without_answers','with_answers'):
                    r = await client.post(f"/api/v1/exam-papers/{p['id']}/export",json={'mode':mode,'include_analysis':False})
                    assert r.status_code == 200, r.text[:200]
                    xml = zipfile.ZipFile(io.BytesIO(r.content)).read('word/document.xml').decode()
                    assert ('参考答案' in xml) == (mode == 'with_answers')
                    if mode == 'with_answers':
                        assert 'w:type="page"' in xml
                    path = output / f"paper-{p['set_index']}-{mode}.docx"
                    path.write_bytes(r.content); artifacts.append(path.name)
            result = {'subject_id':sid,'template_id':tid,'sample_questions':len(ids),'question_ids':ids,
                      'batch_id':batch['id'],'paper_ids':[p['id'] for p in batch['papers']],
                      'preflight':report,'exports':artifacts,'concurrent_replacement_verified':True,'passed':True}
            (output / 'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            return result
    finally:
        app.dependency_overrides.clear(); app.dependency_overrides.update(previous)
        await engine.dispose()


if __name__ == '__main__':
    result = asyncio.run(acceptance(get_db_url(), Path(__file__).resolve().parents[1] / 'backups' / 'flat-tags-v2' / 'acceptance'))
    print(json.dumps({k:v for k,v in result.items() if k in ('passed','subject_id','sample_questions','batch_id','paper_ids')},ensure_ascii=False))
