from fastapi import APIRouter, Request, Body
from app.engine import evaluate
from app.web import render
router = APIRouter()


@router.get('/attribution')
def page(request: Request):
    return render(request, 'attribution')


@router.post('/api/attribution')
def calculate(payload: dict = Body(default={})):
    return evaluate(payload, until=7)
