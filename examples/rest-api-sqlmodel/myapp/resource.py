from typing import Optional

from sqlalchemy import Engine
from sqlmodel import Field, Session, SQLModel, delete, select

from rolo import Request, Response, route


class Hero(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    secret_name: str
    age: Optional[int] = None


class HeroResource:
    db_engine: Engine

    def __init__(self, db_engine: Engine):
        self.db_engine = db_engine

    @route("/heroes", methods=["GET"])
    def list_heroes(self, request: Request) -> list[Hero]:
        with Session(self.db_engine) as session:
            statement = select(Hero)
            results = session.exec(statement)
            return list(results)

    @route("/heroes/<int:hero_id>", methods=["GET"])
    def get_hero(self, request: Request, hero_id: int) -> Hero | Response:
        with Session(self.db_engine) as session:
            statement = select(Hero).where(Hero.id == hero_id)
            results = session.exec(statement)
            if hero := results.first():
                return hero
        return Response.for_json({"message": "not found"}, status=404)

    @route("/heroes", methods=["POST"])
    def add_hero(self, request: Request, hero: Hero) -> Hero:
        with Session(self.db_engine) as session:
            session.add(hero)
            session.commit()
            session.refresh(hero)
        return hero

    @route("/heroes/<int:hero_id>", methods=["DELETE"])
    def delete_hero(self, request: Request, hero_id: int) -> None:
        with Session(self.db_engine) as session:
            statement = delete(Hero).where(Hero.id == hero_id)
            session.exec(statement)
            session.commit()
