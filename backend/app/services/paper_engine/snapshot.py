"""Immutable content and tag snapshots."""
from app.services.question_content import parse_json_field

TYPE_NAMES={"single_choice":"单选题","multiple_choice":"多选题","true_false":"判断题","fill_in_the_blank":"填空题","free_response":"问答题"}

def value(v): return v.value if hasattr(v,"value") else v

def build_content_snapshot(question):
    return {"q_type":value(question.q_type),"options":question.options,"content_revision":question.content_revision,
            **{k:parse_json_field(getattr(question,k)) for k in ("content","answer","thinking","analysis","summary")}}

def build_tag_snapshot(question):
    return [{"id":t.id,"name":t.name,"group_id":t.category_id} for t in question.tags]

def order_items(items,parts):
    part_order={p["key"]:i for i,p in enumerate(parts)}
    section_order={s["key"]:i for p in parts for i,s in enumerate(p["sections"])}
    types={p["key"]:list(dict.fromkeys(s["q_type"] for s in p["sections"])) for p in parts}
    def key(item):
        p=item.part_key;t=value(item.q_type);ts=types.get(p,[])
        return (part_order.get(p,999),ts.index(t) if t in ts else 100+list(TYPE_NAMES).index(t),
                section_order.get(item.section_key,999),item.seq or 0)
    items.sort(key=key)
    for i,item in enumerate(items,1):item.seq=i
    return items
