from pydantic import BaseModel, ConfigDict, Field


class Deposit(BaseModel):
    amount: int = Field(gt=0)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    balance: int
    budget: int
