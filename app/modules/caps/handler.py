from fastapi import APIRouter, Request, Body
from app.engine import evaluate
from app.web import render
router = APIRouter()


@router.get('/caps')
def page(request: Request):
    return render(request, 'caps')


@router.post('/api/caps')
def calculate(payload: dict = Body(default={})):
    return evaluate(payload, until=6)
