import streamlit as st
import pandas as pd
from sqlalchemy import create_engine

@st.cache_resource
def init_connection():
    """Vytvoří a bezpečně udrží připojení do Supabase."""
    db_url = st.secrets["DB_URL"]
    # Vytvoření SQLAlchemy motoru pro rychlou komunikaci s Pandas
    engine = create_engine(db_url)
    return engine

def save_to_db(df, table_name):
    """Nahraje Excel data do databáze (vždy přepíše starou verzi novou)."""
    engine = init_connection()
    with st.spinner(f'Ukládám {table_name} do databáze...'):
        # chunksize=1000 rozseká velká data na menší kousky, aby to nespadlo
        df.to_sql(table_name, engine, if_exists='replace', index=False, chunksize=1000)

def load_from_db(table_name):
    """Bleskově načte tabulku z databáze do aplikace."""
    engine = init_connection()
    try:
        return pd.read_sql_table(table_name, engine)
    except ValueError:
        # Pokud tabulka ještě v databázi neexistuje (např. při prvním spuštění)
        return None
