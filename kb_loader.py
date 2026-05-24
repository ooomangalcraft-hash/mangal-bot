import pandas as pd
import re
from typing import List, Dict

class ProductKB:
    def __init__(self, csv_path: str):
        self.df = pd.read_csv(csv_path, sep=';')
        self.df['Price'] = pd.to_numeric(self.df['Price'], errors='coerce').fillna(0)
        self.products = self.df[
            (self.df['Title'].notna()) & (self.df['Price'] > 0)
        ].to_dict('records')

    def normalize(self, text: str) -> str:
        return re.sub(r'[^\w\sа-яА-ЯёЁ-]', '', str(text).lower().strip())

    def search(self, query: str, top_k: int = 3) -> List[Dict]:
        q_norm = self.normalize(query)
        q_words = set(q_norm.split())
        scored = []
        for p in self.products:
            title = self.normalize(str(p.get('Title', '') or ''))
            desc = self.normalize(
                str(p.get('Description', '') or '') + ' ' +
                str(p.get('Text', '') or '')
            )
            mods = self.normalize(str(p.get('Modifications', '') or ''))
            text = title + ' ' + desc + ' ' + mods
            score = len(q_words & set(text.split()))
            if q_norm in title:
                score += 3
            if score > 0:
                scored.append((score, p))
        scored.sort(key=lambda x: -x[0])
        return [p for _, p in scored[:top_k]]

    def format_product(self, p: Dict) -> str:
        mods = p.get('Modifications', '')
        mod_str = ""
        if pd.notna(mods) and mods:
            mod_str = "\n📦 Варианты:\n" + "\n".join(
                f"  • {m.strip()}" for m in str(mods).split(';') if m.strip()
            )
        price = int(float(p['Price']))
        return (
            f"🔹 *{p['Title']}*\n"
            f"💰 Цена: {price:,} ₽\n"
            f"🏷️ Артикул: {p.get('SKU', '—')}\n"
            f"📝 {str(p.get('Description', '') or '')}\n"
            f"{mod_str}\n"
            f"🔗 Подробнее: https://mangal-craft.shop"
        )
