"""Project CRUD. Scene is stored as JSON text, all coordinates in centimeters."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session, select

from ..db import get_session
from ..models import Project, utcnow
from ..schemas import ProjectCreate, ProjectRead, ProjectSummary, ProjectUpdate

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectSummary])
def list_projects(session: Session = Depends(get_session)):
    rows = session.exec(select(Project).order_by(Project.updated_at.desc())).all()
    return [ProjectSummary(id=p.id, name=p.name, updated_at=p.updated_at) for p in rows]


@router.post("", response_model=ProjectRead, status_code=201)
def create_project(body: ProjectCreate, session: Session = Depends(get_session)):
    project = Project(
        name=body.name,
        floorplan_image_url=body.floorplan_image_url,
        pixels_per_cm=body.pixels_per_cm,
        scene_json=body.scene.model_dump_json(),
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return ProjectRead.from_db(project)


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: int, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return ProjectRead.from_db(project)


@router.put("/{project_id}", response_model=ProjectRead)
def update_project(project_id: int, body: ProjectUpdate, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    data = body.model_dump(exclude_unset=True)
    if "scene" in data and body.scene is not None:
        project.scene_json = body.scene.model_dump_json()
    for key in ("name", "floorplan_image_url", "pixels_per_cm"):
        if key in data:
            setattr(project, key, data[key])
    project.updated_at = utcnow()
    session.add(project)
    session.commit()
    session.refresh(project)
    return ProjectRead.from_db(project)


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    session.delete(project)
    session.commit()
    return Response(status_code=204)
