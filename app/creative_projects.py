"""Authenticated project persistence; model credentials never enter snapshots."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src import creative_projects
from src.creative_guide import Message

from . import auth, model_connections

router = APIRouter(prefix='/creative-projects')


class Snapshot(BaseModel):
    messages: list[Message] = Field(default_factory=list, max_length=40)
    brief: str = Field(default='', max_length=8000)
    input: str = Field(default='', max_length=10000)
    refs: list[str] = Field(default_factory=list, max_length=6)


class Save(BaseModel):
    id: str | None = Field(default=None, max_length=100)
    revision: int = Field(default=0, ge=0)
    title: str = Field(min_length=1, max_length=120)
    payload: Snapshot


def user_id(request):
    user = auth.current_user(request)
    if not user:
        raise HTTPException(401, 'Sign in first.')
    return user['id']


@router.get('')
def listing(request: Request, account_id: int = Depends(auth.current_account_id)):
    return {'projects': creative_projects.list_projects(account_id, user_id(request))}


@router.get('/{project_id}')
def read(project_id: str, request: Request, account_id: int = Depends(auth.current_account_id)):
    row = creative_projects.get(project_id, account_id, user_id(request))
    if row is None:
        raise HTTPException(404, 'Project not found.')
    return row


@router.post('')
def save(body: Save, request: Request, account_id: int = Depends(auth.current_account_id)):
    model_connections.mutation_header(request)
    payload = body.payload.model_dump()
    if len(body.payload.model_dump_json()) > 100000:
        raise HTTPException(400, 'Project is too long. Start a new project with your latest brief.')
    row = creative_projects.save(body.id, account_id, user_id(request), body.title,
                                 payload, body.revision)
    if row is None:
        raise HTTPException(409, 'This project changed in another tab. Reopen it before editing further.')
    return row
