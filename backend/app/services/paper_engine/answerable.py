"""Published content must satisfy the same answer rules as the editor."""
from app.services.question_content import parse_json_field, validate_question_domain

def is_answerable_payload(answer):
    try:
        a=parse_json_field(answer)
        if not isinstance(a,dict):return False
        k=a.get("kind")
        if k=="single_choice":return isinstance(a.get("correct"),str) and bool(a["correct"])
        if k=="multiple_choice":return isinstance(a.get("correct"),list) and bool(a["correct"])
        if k=="true_false":return isinstance(a.get("correct"),bool)
        if k=="fill_in_the_blank":return bool(a.get("blanks"))
        if k=="free_response":return a.get("reference") is not None
    except (ValueError,TypeError):pass
    return False

def is_answerable_question(q):
    if q.deleted_at or q.status!="published" or not is_answerable_payload(q.answer):return False
    try:
        validate_question_domain(q_type=q.q_type,status=q.status,content=parse_json_field(q.content),
                                 options=q.options,answer=parse_json_field(q.answer),partial=False)
        return True
    except (ValueError,TypeError):return False
