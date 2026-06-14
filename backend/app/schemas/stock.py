from pydantic import BaseModel


class StockOut(BaseModel):
    secucode: str
    code: str
    name: str
    market: str

    model_config = {"from_attributes": True}
