import pandas as pd
import numpy as np
import re

# ==========================================
# SLOVNÍKY A KONSTANTY
# ==========================================
QUEUE_DESC = {
    'PI_PL (Mix)': 'Mix Pallet', 'PI_PL (Total)': 'Mix Pallet', 'PI_PL (Single)': 'Mix Pallet',
    'PI_PL_OE (Mix)': 'Mix Pallet OE', 'PI_PA_OE': 'Parcel OE', 'PI_PL_OE (Total)': 'Mix Pallet OE',
    'PI_PL_OE (Single)': 'Mix Pallet OE', 'PI_PA': 'Parcel', 'PI_PA_RU': 'Parcel Express',
    'PI_PL_FU': 'Full Pallet', 'PI_PL_FUOE': 'Full Pallet OE'
}
BOX_UNITS = {'AEK', 'KAR', 'KART', 'PAK', 'VPE', 'CAR', 'BLO', 'ASK', 'BAG', 'PAC'}

def t(key): 
    # Zatím vrací klíč (případně sem později můžeme vrátit celý ten obří slovník pro CZ/EN překlady)
    return key 

# ==========================================
# POMOCNÉ FUNKCE (Čištění a párování)
# ==========================================
def get_match_key_vectorized(series):
    s = series.astype(str).str.strip().str.upper()
    mask_decimal = s.str.match(r'^\d+\.\d+$')
    s = s.copy(); s[mask_decimal] = s[mask_decimal].str.rstrip('0').str.rstrip('.')
    mask_numeric = s.str.match(r'^0+\d+$')
    s[mask_numeric] = s[mask_numeric].str.lstrip('0')
    return s

def get_match_key(val):
    v = str(val).strip().upper()
    if '.' in v and v.replace('.', '').isdigit(): v = v.rstrip('0').rstrip('.')
    if v.isdigit(): v = v.lstrip('0') or '0'
    return v

def parse_packing_time(val):
    v = str(val).strip()
    if v in ['', 'nan', 'None', 'NaN']: return 0.0
    try:
        num = float(v)
        if num < 1.0: return num * 24 * 60
        return num
    except: pass
    parts = v.split(':')
    try:
        if len(parts) == 3: return int(parts[0])*60 + int(parts[1]) + float(parts[2])/60.0
        elif len(parts) == 2: return int(parts[0]) + float(parts[1])/60.0
    except: pass
    return 0.0

# ==========================================
# HLAVNÍ VÝPOČETNÍ MOTOR (Pohyby rukou)
# ==========================================
def fast_compute_moves(qty_list, queue_list, su_list, box_list, w_list, d_list, v_lim, d_lim, h_lim):
    res_total, res_exact, res_miss = [], [], []
    for qty, q, su, boxes, w, d in zip(qty_list, queue_list, su_list, box_list, w_list, d_list):
        if qty <= 0:
            res_total.append(0); res_exact.append(0); res_miss.append(0); continue
        if str(q).upper() in ('PI_PL_FU', 'PI_PL_FUOE') and str(su).strip().upper() == 'X':
            res_total.append(1); res_exact.append(1); res_miss.append(0); continue
        
        if not isinstance(boxes, list): boxes = []
        real_boxes = [b for b in boxes if b > 1]
        pb = pok = pmiss = 0
        zbytek = qty
        
        for b in real_boxes:
            if zbytek >= b:
                m = int(zbytek // b); pb += m; zbytek = zbytek % b
                
        if zbytek > 0:
            if w >= v_lim or d >= d_lim: p = int(zbytek)
            else: p = int(np.ceil(zbytek / h_lim))
            if len(boxes) > 0: pok += p
            else: pmiss += p
            
        res_total.append(pb + pok + pmiss); res_exact.append(pb + pok); res_miss.append(pmiss)
    return res_total, res_exact, res_miss
