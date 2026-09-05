from pydantic import BaseModel, ConfigDict


class BotCreate(BaseModel):
    token: str


class BotUpdate(BaseModel):
    token: str


class BotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    token: str
    running: bool
