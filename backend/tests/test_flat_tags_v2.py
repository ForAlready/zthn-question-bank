"""Flat-tag contract and real API workflow regression, isolated from the dev DB."""
import json
from decimal import Decimal
import pytest
from pydantic import ValidationError
from sqlalchemy import select, func
from app.models import User, Subject, Tag, TagCategory, Question, PaperTemplate, ExamPaperBatch
from app.models.question import QuestionType
from app.schemas.tag_filter import TagFilter
from app.schemas.paper_template import PaperTemplateCreate
from app.core.security import create_access_token

DOC = {"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"测试题目"}]}]}


@pytest.mark.parametrize("ids,selected,mode,expected", [
    ([1,2],[1,3],"any",True),([1,2],[1,3],"all",False),([1,2],[1,2],"all",True),
    ([],[],"any",True),([],[],"all",True),([],[1],"any",False),([1],[1,1],"all",True),
])
def test_tag_matching(ids,selected,mode,expected):
    assert TagFilter(tag_ids=selected,match=mode).matches(ids) is expected


@pytest.mark.parametrize("payload",[{"tag_ids":[0]},{"tag_ids":[True]},{"tag_ids":["1"]},{"tag_ids":None},{"match":"none"},{"category_ids":[1]}])
def test_strict_filter(payload):
    with pytest.raises(ValidationError):TagFilter.model_validate(payload)


@pytest.fixture
async def bank(db_session):
    u=User(username="flat-admin",full_name="管理员",hashed_password="x",is_active=True,is_superuser=True)
    subject=Subject(name="标签验收",slug="flat-test")
    db_session.add_all([u,subject]);await db_session.flush()
    group=TagCategory(name="内容",subject_id=subject.id)
    db_session.add(group);await db_session.flush()
    tags=[Tag(name=n,subject_id=subject.id,category_id=group.id,enabled=True) for n in ("A","B","C","D")]
    db_session.add_all(tags);await db_session.commit()
    return {"user":u,"subject":subject,"group":group,"tags":tags,
            "headers":{"Authorization":"Bearer "+create_access_token(subject=u.id)}}


async def question(client,bank,tags=(),qt="single_choice",status="published"):
    payload={"subject_id":bank["subject"].id,"content":DOC,"q_type":qt,"status":status,"tag_ids":list(tags),
             "answer":{"kind":qt,"correct":"opt_a"} if qt=="single_choice" else {"kind":"free_response","reference":DOC},
             "options":[{"id":"opt_a","label":"A","content":DOC},{"id":"opt_b","label":"B","content":DOC}] if qt=="single_choice" else None}
    r=await client.post('/api/v1/questions',headers=bank['headers'],json=payload)
    assert r.status_code==200,r.text
    return r.json()


def rule(key,ids,count=1,mode="any",qt="single_choice",score=1):
    return {"key":key,"q_type":qt,"tag_filter":{"tag_ids":list(ids),"match":mode},"count":count,"score_each":score}


async def template(client,bank,rules,scope=None):
    total=float(sum(Decimal(str(r['score_each']))*r['count'] for r in rules))
    payload={"subject_id":bank['subject'].id,"name":"验收模板","total_score":total,
             "parts":[{"key":"part","title":"试题","part_score":total,"sections":rules}]}
    if scope is not None:payload['scope']=scope
    r=await client.post('/api/v1/paper-templates',headers=bank['headers'],json=payload)
    assert r.status_code==200,r.text
    return r.json()


async def generate(client,bank,t,**kw):
    return await client.post('/api/v1/exam-papers/generate',headers=bank['headers'],json={"template_id":t['id'],**kw})


async def test_global_match_and_preflight_no_write(client,bank,db_session):
    a,b,*_= [t.id for t in bank['tags']]
    qa=await question(client,bank,[a]);qab=await question(client,bank,[a,b])
    t=await template(client,bank,[rule('broad',[a]),rule('narrow',[b])])
    r=await client.post(f"/api/v1/paper-templates/{t['id']}/preflight",headers=bank['headers'],json={})
    assert r.status_code==200,r.text
    assert r.json()['feasible'] is True
    assert (await db_session.execute(select(func.count()).select_from(ExamPaperBatch))).scalar_one()==0
    r=await generate(client,bank,t)
    assert r.status_code==200,r.text
    items=r.json()['papers'][0]['items']
    assert {i['question_id'] for i in items}=={qa['id'],qab['id']}
    assert {i['section_key'] for i in items}=={'broad','narrow'}


async def test_local_conflict_even_when_union_large(client,bank):
    a,b,*_=[t.id for t in bank['tags']]
    await question(client,bank,[a])
    for _ in range(3):await question(client,bank,[b])
    t=await template(client,bank,[rule('a1',[a]),rule('a2',[a]),rule('b',[b])])
    r=await generate(client,bank,t)
    assert r.status_code==400,r.text
    gaps=r.json()['detail']['gaps']
    assert gaps[0]['code']=='overlapping_pool_conflict'
    assert gaps[0]['deficit']==1 and gaps[0]['available']==1


async def test_batch_global_dedup_and_rollback(client,bank,db_session):
    a=bank['tags'][0].id
    await question(client,bank,[a])
    t=await template(client,bank,[rule('a',[a])])
    r=await generate(client,bank,t,n_sets=2)
    assert r.status_code==400
    assert (await db_session.execute(select(func.count()).select_from(ExamPaperBatch))).scalar_one()==0
    r=await generate(client,bank,t,n_sets=2,cross_set_dedup=False)
    assert r.status_code==200,r.text
    ids=[p['items'][0]['question_id'] for p in r.json()['papers']]
    assert ids[0]==ids[1]


async def test_scope_intersection_and_explicit_clear(client,bank):
    a,b,*_=[t.id for t in bank['tags']]
    await question(client,bank,[a])
    t=await template(client,bank,[rule('a',[a])],scope={"tag_ids":[b],"match":"all"})
    assert (await generate(client,bank,t)).status_code==400
    r=await generate(client,bank,t,scope={"tag_ids":[],"match":"any"})
    assert r.status_code==200,r.text
    assert (await generate(client,bank,t,scope=None)).status_code==422
    fetched=await client.get(f"/api/v1/paper-templates/{t['id']}",headers=bank['headers'])
    assert fetched.json()['scope']['tag_ids']==[b]


async def test_disabled_reference_and_group_protection(client,bank):
    a=bank['tags'][0].id
    await question(client,bank,[a]);t=await template(client,bank,[rule('a',[a])])
    refs=await client.get(f'/api/v1/tags/{a}/references',headers=bank['headers'])
    assert refs.json()['template_count']==1 and refs.json()['question_count']==1
    assert (await client.delete(f'/api/v1/tags/{a}',headers=bank['headers'])).status_code==409
    assert (await client.delete(f"/api/v1/tag-categories/{bank['group'].id}",headers=bank['headers'])).status_code==409
    r=await client.put(f'/api/v1/tags/{a}',headers=bank['headers'],json={"enabled":False})
    assert r.status_code==200,r.text
    assert (await generate(client,bank,t)).status_code==400


async def test_metadata_and_atomic_batch(client,bank):
    a,b,*_=[t.id for t in bank['tags']]
    q=await question(client,bank,[a])
    r=await client.put(f"/api/v1/questions/{q['id']}",headers=bank['headers'],json={"tag_ids":[b]})
    assert r.status_code==200,r.text
    assert r.json()['answer']==q['answer'] and r.json()['content_revision']==q['content_revision']
    r=await client.post('/api/v1/questions/batch-tags',headers=bank['headers'],json={"ids":[q['id'],999999],"tag_ids":[a],"operation":"append"})
    assert r.status_code==404,r.text
    q2=(await client.get(f"/api/v1/questions/{q['id']}",headers=bank['headers'])).json()
    assert [t['id'] for t in q2['tags']]==[b]
    for op,ids,expected in [('append',[a],{a,b}),('remove',[a],{b}),('replace',[a],{a}),('clear',[],set())]:
        r=await client.post('/api/v1/questions/batch-tags',headers=bank['headers'],json={"ids":[q['id']],"tag_ids":ids,"operation":op})
        assert r.status_code==200,r.text
        q2=(await client.get(f"/api/v1/questions/{q['id']}",headers=bank['headers'])).json()
        assert {t['id'] for t in q2['tags']}==expected


async def test_list_tag_modes_and_legacy_rejection(client,bank):
    a,b,*_=[t.id for t in bank['tags']]
    await question(client,bank,[a]);await question(client,bank,[a,b])
    base=f"/api/v1/questions?subject_id={bank['subject'].id}&tag_ids={a}&tag_ids={b}"
    assert (await client.get(base+'&tag_match=any',headers=bank['headers'])).json()['total']==2
    assert (await client.get(base+'&tag_match=all',headers=bank['headers'])).json()['total']==1
    assert (await client.get(base+'&category_ids=1',headers=bank['headers'])).status_code==422
    for route in ['categories','category-dimensions','question-types/tree']:
        assert (await client.get('/api/v1/'+route,headers=bank['headers'])).status_code==404


async def test_cross_subject_invalid_tags(client,bank,db_session):
    other=Subject(name='其他',slug='flat-other');db_session.add(other);await db_session.flush()
    tag=Tag(name='其他标签',subject_id=other.id);db_session.add(tag);await db_session.commit()
    payload={"subject_id":bank['subject'].id,"name":"无效","total_score":1,
             "parts":[{"key":"p","title":"题","part_score":1,"sections":[rule('r',[tag.id])]}]}
    r=await client.post('/api/v1/paper-templates',headers=bank['headers'],json=payload)
    assert r.status_code==400,r.text


async def test_replace_score_finalize_and_export(client,bank):
    a,b,*_=[t.id for t in bank['tags']]
    for _ in range(3):await question(client,bank,[a])
    fr=await question(client,bank,[b],qt='free_response')
    t=await template(client,bank,[rule('a',[a],score=2)])
    r=await generate(client,bank,t);assert r.status_code==200,r.text
    paper=r.json()['papers'][0];pid=paper['id'];item=paper['items'][0]
    path=f"/api/v1/exam-papers/{pid}"
    r=await client.post(f"{path}/items/{item['id']}/replace",headers=bank['headers'],json={"mode":"random_same_type"})
    assert r.status_code==200,r.text
    assert r.json()['items'][0]['question_id']!=item['question_id']
    r=await client.post(f"{path}/items/{item['id']}/replace",headers=bank['headers'],json={"mode":"manual","question_id":fr['id']})
    assert r.status_code==409,r.text
    r=await client.post(f"{path}/items/{item['id']}/replace",headers=bank['headers'],json={"mode":"manual","question_id":fr['id'],"accept_template_deviation":True})
    assert r.status_code==200,r.text
    assert r.json()['items'][0]['section_key']=='a' and r.json()['template_warnings']
    r=await client.patch(f"{path}/items/{item['id']}",headers=bank['headers'],json={"score":4.5})
    assert r.status_code==200,r.text
    assert float(r.json()['actual_total_score'])==4.5
    assert (await client.post(path+'/finalize',headers=bank['headers'])).status_code==200
    assert (await client.patch(f"{path}/items/{item['id']}",headers=bank['headers'],json={"score":1})).status_code==409
    import io,zipfile
    for mode in ['without_answers','with_answers']:
        r=await client.post(path+'/export',headers=bank['headers'],json={"mode":mode,"include_analysis":False})
        assert r.status_code==200,r.text
        xml=zipfile.ZipFile(io.BytesIO(r.content)).read('word/document.xml').decode()
        assert ('参考答案' in xml)==(mode=='with_answers')
        if mode=='with_answers':assert 'w:type="page"' in xml


async def test_default_seed_idempotent(client,bank,db_session):
    from scripts.seed_flat_tags_v2 import seed_subject
    first=await seed_subject(db_session,bank['subject']);await db_session.commit()
    second=await seed_subject(db_session,bank['subject']);await db_session.commit()
    assert first.id==second.id
    parts=first.parts_json
    assert len([s for p in parts for s in p['sections']])==12
    assert sum(s['count'] for p in parts for s in p['sections'])==25
    assert sum(s['count']*s['score_each'] for p in parts for s in p['sections'])==100


async def test_changed_candidate_rolls_back_whole_batch(client, bank, db_session, monkeypatch):
    from sqlalchemy import update
    from app.services.paper_engine import generate as engine
    a = bank['tags'][0].id
    q = await question(client, bank, [a])
    t = await template(client, bank, [rule('a', [a])])
    original = engine.prepare
    async def change_after_plan(db, **kwargs):
        result = await original(db, **kwargs)
        await db.execute(update(Question).where(Question.id == q['id']).values(status='archived')
                         .execution_options(synchronize_session=False))
        return result
    monkeypatch.setattr(engine, 'prepare', change_after_plan)
    r = await generate(client, bank, t)
    assert r.status_code == 409, r.text
    assert r.json()['detail']['code'] == 'candidate_changed'
    assert (await db_session.execute(select(func.count()).select_from(ExamPaperBatch))).scalar_one() == 0
    assert (await client.get(f"/api/v1/questions/{q['id']}", headers=bank['headers'])).json()['status'] == 'published'


async def test_import_type_aliases_unknown_and_existing_tags(client, bank, db_session):
    from app.services.structured_parser import parse_structured
    from app.services.importing.review import extracted_to_v2_review
    from app.api.v1.endpoints.upload import _as_review
    for name in ['简答', '论述题', '案例分析']:
        result = parse_structured(f'【题目】说明理由\n【题型】{name}\n【答案】参考说明\n【标签】A，不存在的新标签')
        result = await _as_review({'questions': result.questions}, bank['subject'].id, db_session)
        assert result['questions'][0]['q_type'] == 'free_response'
        assert result['questions'][0]['tag_ids'] == [bank['tags'][0].id]
        assert result['questions'][0]['ai_suggested_tags']['ai_extracted'] == ['A', '不存在的新标签']
    unknown = extracted_to_v2_review([{'q_type': '配对题', 'content': '题干', 'options': ['A.甲', 'B.乙'], 'answer': 'A'}])[0]
    assert unknown['q_type'] is None and unknown['warnings'] and len(unknown['options']) == 2
    assert unknown['raw_answer'] == 'A'
    ambiguous = parse_structured('【题目】选择\n【选项】A.甲\nB.乙').questions[0]
    assert ambiguous['q_type'] is None
    assert (await db_session.execute(select(func.count()).select_from(Tag))).scalar_one() == 4


async def test_same_type_rules_decimal_scores_and_snapshot(client, bank):
    import io, zipfile
    a,b,*_ = [t.id for t in bank['tags']]
    await question(client,bank,[a]); await question(client,bank,[b])
    t = await template(client,bank,[rule('a',[a],score=0.1),rule('b',[b],score=0.2)])
    r = await generate(client,bank,t)
    assert r.status_code == 200,r.text
    p = r.json()['papers'][0]
    assert p['actual_total_score'] == 0.3
    assert [i['section_key'] for i in p['items']] == ['a','b']
    await client.put(f'/api/v1/tags/{a}',headers=bank['headers'],json={'name':'改名'})
    snapshot = (await client.get(f"/api/v1/exam-papers/{p['id']}",headers=bank['headers'])).json()
    assert snapshot['items'][0]['tag_snapshot_json'][0]['name'] == 'A'
    exported = await client.post(f"/api/v1/exam-papers/{p['id']}/export",headers=bank['headers'],json={'mode':'without_answers'})
    assert exported.status_code == 200,exported.text
    xml = zipfile.ZipFile(io.BytesIO(exported.content)).read('word/document.xml').decode()
    assert xml.count('单选题') == 1


async def test_preflight_excludes_private_invalid_unpublished(client,bank,db_session,grant_role):
    from app.models.subject_member import SubjectMember
    a = bank['tags'][0].id
    public = await question(client,bank,[a])
    private = await question(client,bank,[a])
    await client.put(f"/api/v1/questions/{private['id']}",headers=bank['headers'],json={'visibility':'private'})
    await question(client,bank,[a],status='draft')
    dirty = Question(subject_id=bank['subject'].id, q_type=QuestionType.SINGLE_CHOICE, content=json.dumps(DOC),
                     answer=None, options=[], status='published', visibility='public', tags=[bank['tags'][0]])
    editor = User(username='flat-editor',hashed_password='x',is_active=True,is_superuser=False)
    db_session.add_all([dirty,editor]); await db_session.flush()
    db_session.add(SubjectMember(user_id=editor.id,subject_id=bank['subject'].id,role='editor'));await db_session.commit()
    t = await template(client,bank,[rule('a',[a])])
    headers = {'Authorization':'Bearer '+create_access_token(subject=editor.id)}
    r = await client.post(f"/api/v1/paper-templates/{t['id']}/preflight",headers=headers,json={})
    assert r.status_code == 200,r.text
    assert r.json()['rules'][0]['candidate_count'] == 1
    r = await client.post('/api/v1/exam-papers/generate',headers=headers,json={'template_id':t['id']})
    assert r.status_code == 200,r.text
    p = r.json()['papers'][0]
    assert p['items'][0]['question_id'] == public['id']
    assert (await client.post(f"/api/v1/exam-papers/{p['id']}/export",headers=headers,
                              json={'mode':'with_answers'})).status_code == 403
    assert (await client.post(f"/api/v1/exam-papers/{p['id']}/export",headers=headers,
                              json={'mode':'without_answers'})).status_code == 200
    assert (await client.delete(f"/api/v1/paper-templates/{t['id']}",headers=bank['headers'])).status_code == 409
    r = await client.post(f"/api/v1/exam-papers/{p['id']}/items/{p['items'][0]['id']}/replace",headers=headers,
                          json={'mode':'manual','question_id':private['id'],'accept_template_deviation':True})
    assert r.status_code == 400,r.text


async def test_persistence_failure_rolls_back_all_papers(client, bank, db_session, monkeypatch):
    from app.services.paper_engine import generate as engine
    a = bank['tags'][0].id
    for _ in range(2): await question(client, bank, [a])
    t = await template(client, bank, [rule('a',[a])])
    real = engine.build_content_snapshot
    calls = 0
    def fail_on_second(q):
        nonlocal calls
        calls += 1
        if calls == 2: raise RuntimeError('simulated persistence failure')
        return real(q)
    monkeypatch.setattr(engine,'build_content_snapshot',fail_on_second)
    with pytest.raises(Exception):
        await generate(client,bank,t,n_sets=2)
    assert (await db_session.execute(select(func.count()).select_from(ExamPaperBatch))).scalar_one() == 0


async def test_startup_rejects_legacy_schema(db_session):
    from sqlalchemy import text
    from app.db.migrations import ensure_schema_current, SchemaVersionError
    await db_session.execute(text('CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)'))
    await db_session.execute(text("INSERT INTO alembic_version VALUES ('f7a8b9c0d1e2')"))
    with pytest.raises(SchemaVersionError): await ensure_schema_current(db_session)
    await db_session.execute(text("UPDATE alembic_version SET version_num='a1f2e3d4c5b6'"))
    await ensure_schema_current(db_session)


async def test_ai_tools_only_current_enabled_tags(bank,db_session):
    from app.ai.tools.questions import resolve_tags
    from app.ai.tools.library import get_available_tags
    from app.capabilities.context import ExecutionContext,Surface
    other=Subject(name='AI其他',slug='ai-other');db_session.add(other);await db_session.flush()
    foreign=Tag(name='A',subject_id=other.id);db_session.add(foreign)
    bank['tags'][1].enabled=False
    await db_session.commit()
    assert await resolve_tags(db_session,['A','B'],subject_id=bank['subject'].id)==[bank['tags'][0].id]
    ctx=ExecutionContext(db=db_session,actor=bank['user'],surface=Surface.CHAT,subject_id=bank['subject'].id)
    result=await get_available_tags(ctx,{})
    assert f"ID={bank['tags'][0].id}" in result.content
    assert f"ID={foreign.id}" not in result.content and f"ID={bank['tags'][1].id}" not in result.content
