"""Default paper rules use stable flat tag seeds."""
from sqlalchemy import select
from app.models.tag import Tag

JUNIOR_SEED_KEY="junior_post_exam"
JUNIOR_TEMPLATE_NAME="初级岗考核卷"
JUNIOR_TOTAL_SCORE=100
JUNIOR_INSTRUCTIONS="请独立完成；客观题涂清选项；问答题简述要点。"
JUNIOR_SCOPE={"tag_ids":[],"match":"any"}
BUSINESS_CATEGORY_SEEDS=["idle_trade","recycled_inventory","lease","disposal","store_lease"]

class FactoryRestoreError(ValueError):
    def __init__(self,message):super().__init__(message);self.message=message

async def build_junior_factory_parts(db,*,subject_id):
    keys=["business","technical",*BUSINESS_CATEGORY_SEEDS]
    rows=(await db.execute(select(Tag).where(Tag.subject_id==subject_id,Tag.seed_key.in_(keys)))).scalars().all()
    tags={t.seed_key:t for t in rows}
    if any(k not in tags or not tags[k].enabled for k in keys):
        raise FactoryRestoreError("缺少或停用了默认模板的种子标签，请先初始化或恢复标签")
    def rule(key,qt,ids,count,score):
        return {"key":key,"q_type":qt,"tag_filter":{"tag_ids":ids,"match":"all"},"count":count,"score_each":score}
    biz=[]
    for key,count in zip(BUSINESS_CATEGORY_SEEDS,[2,2,1,3,2]):
        biz.append(rule("biz_sc_"+key,"single_choice",[tags["business"].id,tags[key].id],count,3))
    for key,count in [("recycled_inventory",2),("store_lease",1),("lease",1),("disposal",1)]:
        biz.append(rule("biz_fr_"+key,"free_response",[tags["business"].id,tags[key].id],count,4))
    tech=[rule("tech_"+qt,qt,[tags["technical"].id],count,5)
          for qt,count in [("single_choice",5),("multiple_choice",3),("free_response",2)]]
    return {"schema_version":2,"name":JUNIOR_TEMPLATE_NAME,"total_score":100,
            "parts_json":[{"key":"business","title":"业务类","part_score":50,"sections":biz},
                          {"key":"technical","title":"技术类","part_score":50,"sections":tech}],
            "scope_json":JUNIOR_SCOPE.copy(),"instructions":JUNIOR_INSTRUCTIONS}
