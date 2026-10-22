"""Regression: recognized Chinese type names must not lose their answers."""
import pytest

from app.core.security import create_access_token
from app.models import Subject, User
from app.models.question import QuestionType
from app.schemas.ai import AIQuestion
from app.services.importing.normalize import coerce_q_type
from app.services.importing.review import extracted_to_v2_review
from app.services.question_content_converter import rich_doc_to_plain_text
from app.services.question_type_names import resolve_import_q_type
from app.services.structured_parser import _map_q_type, parse_structured


JAVA_SINGLE = """【题目】Java中，以下哪项是正确的变量声明语句？
【题型】单项选择题
【选项】A. int x = 5;
B. x int = 5;
C. int = x 5;
D. 5 = int x;
【答案】A
【难度】2"""

AI_CASES = [
    ('单项选择题', ['A. final','B. const'], 'A', 'single_choice'),
    ('多项选择题', ['A. int','B. long','C. unknown'], 'AB', 'multiple_choice'),
    ('判断题', None, '错', 'true_false'),
    ('填空题', None, [['int','long']], 'fill_in_the_blank'),
    ('论述题', None, '类是模板，对象是实例。', 'free_response'),
]


def without_optional_nulls(value):
    if isinstance(value, dict):
        return {k:without_optional_nulls(v) for k,v in value.items() if v is not None}
    if isinstance(value, list):
        return [without_optional_nulls(v) for v in value]
    return value


@pytest.mark.parametrize("name,expected", [
    (name, kind) for kind, names in [
        ("single_choice", ["单选", "单选题", "单项选择", "单项选择题", "single_choice"]),
        ("multiple_choice", ["多选", "多选题", "多项选择", "多项选择题", "multiple_choice"]),
        ("true_false", ["判断", "判断题", "是非", "是非题", "true_false"]),
        ("fill_in_the_blank", ["填空", "填空题", "fill_in_the_blank"]),
        ("free_response", ["问答题", "简答题", "论述题", "案例分析题", "主观题", "free_response"]),
    ] for name in names
])
def test_template_ai_and_save_share_type_names(name, expected):
    assert _map_q_type(name) == expected
    assert coerce_q_type(name).value == expected
    assert AIQuestion(q_type=name, content="题干").q_type.value == expected


def test_screenshot_single_choice_keeps_answer_and_option_labels():
    raw = parse_structured(JAVA_SINGLE).questions[0]
    assert raw['q_type'] == 'single_choice'
    reviewed = extracted_to_v2_review([raw])[0]
    assert reviewed['q_type'] == 'single_choice'
    assert reviewed['warnings'] == []
    assert reviewed['answer'] == {'kind':'single_choice','correct':reviewed['options'][0]['id']}
    assert [o['label'] for o in reviewed['options']] == ['A','B','C','D']
    assert rich_doc_to_plain_text(reviewed['options'][0]['content']) == 'int x = 5;'
    assert reviewed['status'] == 'pending'


def test_ai_enum_survives_extraction_model_dump():
    extracted = AIQuestion(q_type='单项选择题', content='Java变量声明', options=['A. int x = 5;', 'B. x int;'], answer='A')
    raw = extracted.model_dump()
    assert raw['q_type'].value == 'single_choice'
    reviewed = extracted_to_v2_review([raw])[0]
    assert reviewed['q_type'] == 'single_choice'
    assert reviewed['answer']['correct'] == reviewed['options'][0]['id']


@pytest.mark.parametrize('name,options,answer,kind', AI_CASES)
def test_ai_five_types_keep_structured_answers(name, options, answer, kind):
    model = AIQuestion(q_type=name,content='Java基础知识____',options=options,answer=answer)
    # AI text extraction revalidates restored images through AIQuestion again.
    raw = AIQuestion(**model.model_dump()).model_dump()
    reviewed = extracted_to_v2_review([raw])[0]
    assert reviewed['q_type'] == kind and reviewed['answer']['kind'] == kind
    assert reviewed['warnings'] == []
    if kind == 'single_choice':
        assert reviewed['answer']['correct'] == reviewed['options'][0]['id']
    elif kind == 'multiple_choice':
        assert reviewed['answer']['correct'] == [o['id'] for o in reviewed['options'][:2]]
    elif kind == 'true_false':
        assert reviewed['answer']['correct'] is False
    elif kind == 'fill_in_the_blank':
        assert [rich_doc_to_plain_text(a) for a in reviewed['answer']['blanks'][0]['accept']] == ['int','long']
    else:
        assert rich_doc_to_plain_text(reviewed['answer']['reference']) == answer


@pytest.mark.parametrize('name,options,answer,kind', AI_CASES)
def test_missing_answers_are_not_fabricated(name, options, answer, kind):
    reviewed = extracted_to_v2_review([{'q_type':name,'content':'需要补充答案','options':options}])[0]
    assert reviewed['q_type'] == kind
    assert reviewed['answer'] is None and reviewed['status'] == 'draft'


def test_missing_normalized_type_can_use_known_original_name():
    raw = {'q_type':None,'raw_type_name':'单项选择题','content':'Java变量声明',
           'options':['A. int x = 5;','B. x int;'],'answer':'A','warnings':['无法确定题型，请复核选择']}
    assert resolve_import_q_type(raw) == QuestionType.SINGLE_CHOICE
    reviewed = extracted_to_v2_review([raw])[0]
    assert reviewed['answer']['kind'] == 'single_choice'
    assert reviewed['answer']['correct'] == reviewed['options'][0]['id']
    assert reviewed['warnings'] == []


def test_unknown_and_conflicting_answers_still_require_review():
    raw = {'q_type':'配对题','raw_type_name':'单项选择题','content':'需要复核',
           'options':['A. 甲','B. 乙'],'answer':'A'}
    unknown = extracted_to_v2_review([raw])[0]
    assert unknown['q_type'] is None and unknown['answer'] is None
    assert unknown['raw_answer'] == 'A' and unknown['warnings']
    assert rich_doc_to_plain_text(unknown['options'][0]['content']) == '甲'
    conflict = extracted_to_v2_review([{**raw,'q_type':'单项选择题','answer':'AB'}])[0]
    assert conflict['q_type'] == 'single_choice' and conflict['answer'] is None
    assert conflict['raw_answer'] == 'AB' and conflict['warnings']


def test_review_metadata_is_safe_when_saving_as_composition():
    from app.models.question import QuestionStatus
    from app.services.paper_import_service import _build_question_create
    reviewed = extracted_to_v2_review(parse_structured(JAVA_SINGLE).questions)[0]
    payload = _build_question_create(reviewed,subject_id=1,default_status=QuestionStatus.PENDING,source='java.md')
    assert payload.q_type == QuestionType.SINGLE_CHOICE
    assert payload.answer.correct == payload.options[0].id


async def test_ten_questions_upload_review_save_reopen(client, db_session):
    user = User(username='type-import-admin',hashed_password='x',is_active=True,is_superuser=True)
    subject = Subject(name='导入题型回归',slug='type-import-regression')
    db_session.add_all([user,subject]); await db_session.commit()
    headers = {'Authorization':'Bearer '+create_access_token(subject=user.id)}
    blocks = [
        JAVA_SINGLE,
        JAVA_SINGLE.replace('单项选择题','单项选择').replace('【答案】A','【答案】B'),
        JAVA_SINGLE.replace('单项选择题','单选题'),
        JAVA_SINGLE.replace('单项选择题','多项选择题').replace('【答案】A','【答案】AB'),
        JAVA_SINGLE.replace('单项选择题','多项选择').replace('【答案】A','【答案】AC'),
        '【题目】Java支持面向对象。\n【题型】是非题\n【答案】对',
        '【题目】Java中所有整数均为负数。\n【题型】判断题\n【答案】错',
        '【题目】Java的整数类型有____。\n【题型】填空题\n【答案】[["int"]]',
        '【题目】说明类和对象的区别。\n【题型】简答题\n【答案】类是模板，对象是实例。',
        '【题目】分析给定场景的处理过程。\n【题型】案例分析题\n【答案】先确认输入，再处理异常。',
    ]
    r = await client.post('/api/v1/upload/markdown-text',headers=headers,json={
        'content':'\n\n'.join(blocks),'filename':'java-types-regression.md','method':'structured','subject_id':subject.id})
    assert r.status_code == 200,r.text
    reviewed = r.json()['questions']
    assert len(reviewed) == 10
    assert [q['q_type'] for q in reviewed] == ['single_choice']*3+['multiple_choice']*2+['true_false']*2+['fill_in_the_blank']+['free_response']*2
    assert all(q['answer'] and not q['warnings'] for q in reviewed)
    assert reviewed[0]['answer']['correct'] == reviewed[0]['options'][0]['id']
    assert reviewed[1]['answer']['correct'] == reviewed[1]['options'][1]['id']
    assert reviewed[5]['answer']['correct'] is True
    assert reviewed[6]['answer']['correct'] is False
    fields = {'q_type','content','options','answer','thinking','analysis','summary','difficulty','status','subject_id','tag_ids','knowledge_point_ids'}
    r = await client.post('/api/v1/questions/batch',headers=headers,json={
        'questions':[{k:v for k,v in q.items() if k in fields} for q in reviewed]})
    assert r.status_code == 200,r.text
    for expected, saved in zip(reviewed,r.json()):
        reopened = await client.get(f"/api/v1/questions/{saved['id']}",headers=headers)
        assert reopened.status_code == 200,reopened.text
        assert reopened.json()['q_type'] == expected['q_type']
        # API schemas add optional grading/match defaults; answer data must match.
        assert without_optional_nulls(reopened.json()['answer']) == expected['answer']


async def test_worker_import_keeps_all_five_ai_enum_answers(db_session):
    from app.services.importing.normalize import QuestionImporter
    from app.services.importing.contracts import ImportDefaults
    from app.models.question import QuestionStatus
    from app.services.question_content import parse_json_field
    user = User(username='worker-types',hashed_password='x',is_active=True,is_superuser=True)
    subject = Subject(name='批量导入题型',slug='worker-types')
    db_session.add_all([user,subject]);await db_session.commit()
    raws = [AIQuestion(q_type=name,content='Java基础知识____',options=options,answer=answer).model_dump()
            for name,options,answer,_ in AI_CASES]
    report = await QuestionImporter().import_batch(db_session,raws,user_id=user.id,import_task_id=None,
        defaults=ImportDefaults(subject_id=subject.id,status=QuestionStatus.PENDING))
    assert not report.failed and len(report.created) == 5
    for row,(_,_,_,kind) in zip(report.created,AI_CASES):
        assert row.q_type.value == kind
        assert parse_json_field(row.answer)['kind'] == kind
