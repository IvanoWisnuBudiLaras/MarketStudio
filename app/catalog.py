"""Public catalog rendering from an approved, allowlisted snapshot."""

from html import escape
from typing import Any


def render_catalog(snapshot: dict[str, Any]) -> str:
    name = escape(snapshot["name"])
    cards = []
    for item in snapshot["offerings"]:
        price = f'{item["unit_price_idr"]:,}'.replace(",", ".")
        kind = "Jasa" if item["offering_type"] == "service" else "Barang"
        cards.append(
            f'<li><p class="kind">{kind}</p><h2>{escape(item["name"])}</h2>'
            f'<p class="price">Rp {price} / {escape(item["unit"])}</p></li>'
        )

    artwork = ""
    if asset := snapshot["asset"]:
        artwork = (
            f'<figure><img src="data:image/png;base64,{escape(asset["image"])}" '
            f'alt="{escape(asset["title"])}"><figcaption>{escape(asset["attribution"])}'
            f' · {escape(asset["license"])}</figcaption></figure>'
        )

    return f"""<!doctype html>
<html lang="id">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Katalog {name}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: #F7F8FA; color: #172033; font: 16px system-ui, sans-serif; }}
  main {{ max-width: 1040px; padding: clamp(16px, 4vw, 40px); margin: auto; overflow-wrap: anywhere; }}
  header {{ background: #142B52; color: #fff; padding: clamp(20px, 5vw, 48px); border-radius: 8px; }}
  h1 {{ margin: 4px 0 0; font-size: clamp(24px, 5vw, 36px); }}
  header p {{ color: #BFDBFE; margin: 0; }}
  .content {{ display: grid; gap: 24px; margin-top: 24px; align-items: start; }}
  @media (min-width: 720px) {{ .with-art {{ grid-template-columns: 1fr 2fr; }} }}
  figure, li {{ margin: 0; background: #fff; border: 1px solid #E2E6EC; border-radius: 8px; }}
  figure {{ padding: 12px; }}
  img {{ display: block; width: 100%; max-height: 300px; object-fit: contain; border-radius: 4px; }}
  figcaption {{ margin-top: 8px; font-size: 14px; color: #475569; }}
  ul {{ list-style: none; padding: 0; margin: 0; display: grid; gap: 12px;
    grid-template-columns: repeat(auto-fit, minmax(min(190px, 100%), 1fr)); }}
  li {{ padding: 16px; }}
  li h2 {{ font-size: 18px; margin: 4px 0 12px; }}
  .kind {{ font-size: 14px; color: #475569; margin: 0; }}
  .price {{ color: #142B52; font-weight: 700; font-variant-numeric: tabular-nums; margin: 0; }}
</style>
</head>
<body>
<main>
  <header><p>Katalog produk dan jasa</p><h1>{name}</h1></header>
  <div class="content{' with-art' if artwork else ''}">
    {artwork}
    <ul aria-label="Produk dan jasa">{''.join(cards)}</ul>
  </div>
</main>
</body>
</html>"""
