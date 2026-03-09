import os
import streamlit as st
from supabase import create_client, Client
import pandas as pd
import io

# Inicializace klienta Supabase
try:
    url: str = st.secrets["SUPABASE_URL"]
    key: str = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(url, key)
except Exception as e:
    st.error("Chyba připojení k databázi. Zkontrolujte st.secrets.")
    supabase = None

# Název bucketu, který jsi vytvořil v Supabase Storage
BUCKET_NAME = "warehouse_data"

def save_to_db(df, name):
    """
    Extrémně efektivní ukládání: Zkomprimuje DataFrame do formátu Parquet 
    a uloží jako jediný malý soubor do Supabase Storage.
    """
    if supabase is None or df is None or df.empty:
        return False
        
    try:
        # 1. Převedeme data na zkomprimovaný binární Parquet
        buffer = io.BytesIO()
        df.to_parquet(buffer, engine='pyarrow', index=False)
        buffer.seek(0)
        file_bytes = buffer.read()
        
        file_path = f"{name}.parquet"
        
        # 2. Smažeme starý soubor, pokud existuje (Storage nepodporuje přímý overwrite jednoduše)
        try:
            supabase.storage.from_(BUCKET_NAME).remove([file_path])
        except:
            pass # Pokud soubor neexistoval, nic se neděje
            
        # 3. Nahrajeme nový komprimovaný soubor
        supabase.storage.from_(BUCKET_NAME).upload(file_path, file_bytes)
        return True
        
    except Exception as e:
        st.error(f"Chyba při ukládání {name} do Storage: {e}")
        return False

def load_from_db(name):
    """
    Extrémně rychlé čtení: Stáhne komprimovaný 2MB soubor a rozbalí ho 
    přímo do Pandas DataFrame. Šetří gigabyty dat na síti.
    """
    if supabase is None:
        return None
        
    try:
        file_path = f"{name}.parquet"
        
        # 1. Stáhneme binární soubor ze Storage
        response = supabase.storage.from_(BUCKET_NAME).download(file_path)
        
        # 2. Převedeme binární data zpět na DataFrame
        buffer = io.BytesIO(response)
        df = pd.read_parquet(buffer, engine='pyarrow')
        return df
        
    except Exception as e:
        # Soubor na Supabase zatím neexistuje (uživatel ho ještě nenahrál v Admin zóně)
        return None
