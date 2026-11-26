from sqlmodel import Session, select

from app.models import Product
from app.services.catalog_snapshot import export_catalog, import_catalog


def test_snapshot_round_trip_keeps_ids_and_resets_models(engine, tmp_path):
    from app import db

    db.init_db()
    with Session(engine) as s:
        s.add(Product(id=7, product_url="https://x/1", title="ספה", category="sofa", price_ils=999, width_cm=200,
                      depth_cm=90, height_cm=80, image_url="https://x/1.jpg", model_status="ready", model_3d_url="/static/models/7.glb"))
        s.commit()
        path = tmp_path / "c.json.gz"
        assert export_catalog(s, path) == 1
    with Session(engine) as s:
        s.delete(s.get(Product, 7))
        s.commit()
        assert import_catalog(s, path) == 1
        assert import_catalog(s, path) == 0  # idempotent
        p = s.exec(select(Product)).one()
        assert (p.id, p.title, p.width_cm) == (7, "ספה", 200)
        assert p.model_status == "none" and p.model_3d_url is None
