from pydantic import BaseModel, ConfigDict, Field


class RatioUpdate(BaseModel):
    ratio: float | None = Field(default=None, gt=0)
    oauth_ratio: float | None = Field(default=None, gt=0)


class RatioRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ratio: float
    oauth_ratio: float
