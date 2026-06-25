from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from app.deps import get_current_user
from app.models import portfolio as pf

router = APIRouter()


class AddBody(BaseModel):
    symbol: str
    type: Literal["stock", "fund"]
    market: Literal["cn", "hk", "us"] = "cn"
    name: str | None = None
    quantity: float | None = None
    cost_price: float | None = None


@router.post("/portfolio", status_code=201)
def add(body: AddBody, user=Depends(get_current_user)):
    pid = pf.add_portfolio(
        user["id"], body.symbol, body.name, body.type,
        body.market, body.quantity, body.cost_price,
    )
    return {"id": pid}


@router.get("/portfolio")
def list_(user=Depends(get_current_user)):
    rows = pf.list_portfolios(user["id"])
    return [
        {
            "id": r["id"],
            "symbol": r["symbol"],
            "name": r["name"],
            "type": r["type"],
            "market": r["market"],
            "quantity": float(r["quantity"]) if r["quantity"] is not None else None,
            "cost_price": float(r["cost_price"]) if r["cost_price"] is not None else None,
        }
        for r in rows
    ]


@router.delete("/portfolio/{pid}", status_code=204)
def delete(pid: int, user=Depends(get_current_user)):
    if not pf.delete_portfolio(pid, user["id"]):
        raise HTTPException(status_code=404, detail="portfolio not found")
    return Response(status_code=204)
