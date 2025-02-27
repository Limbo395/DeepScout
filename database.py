from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

engine = create_engine('sqlite:///deepscout.db', echo=False)
Base = declarative_base()

class Search(Base):
    __tablename__ = 'searches'

    id = Column(Integer, primary_key=True)
    query = Column(Text)
    search_type = Column(Text)
    response = Column(Text)
    chat_history = Column(Text)  # JSON string storing conversation history

    webpages = relationship("WebPage", back_populates="search")

    def __repr__(self):
        return f"<Search(query='{self.query}', type='{self.search_type}')>"

class WebPage(Base):
    __tablename__ = 'webpages'

    id = Column(Integer, primary_key=True)
    search_id = Column(Integer, ForeignKey('searches.id'))
    url = Column(Text)
    title = Column(Text)
    icon_url = Column(Text)
    content = Column(Text)

    search = relationship("Search", back_populates="webpages")

    def __repr__(self):
        return f"<WebPage(url='{self.url}', title='{self.title}')>"

def create_tables():
    Base.metadata.create_all(engine)

def get_session():
    Session = sessionmaker(bind=engine)
    return Session()

if __name__ == '__main__':
    create_tables()
    print("База даних і таблиці створені!")