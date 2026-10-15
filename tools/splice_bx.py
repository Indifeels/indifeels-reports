"""Dev helper: copies tools/restock_bx.css / restock_bx.js into the marker blocks of both restock templates
(the templates are shipped as single self-contained pages)."""
import os, re, sys
T = os.path.dirname(os.path.abspath(__file__))
css = open(os.path.join(T, "restock_bx.css"), encoding="utf-8").read().strip()
js = open(os.path.join(T, "restock_bx.js"), encoding="utf-8").read().strip()
for f in ("restock_supplier_template.html", "restock_plan_template.html"):
    p = os.path.join(T, f); s = open(p, encoding="utf-8").read()
    s2 = re.sub(r"/\*BXCSS_START\*/.*?/\*BXCSS_END\*/", lambda m: css, s, flags=re.S)
    s2 = re.sub(r"/\*BXJS_START\*/.*?/\*BXJS_END\*/", lambda m: js, s2, flags=re.S)
    open(p, "w", encoding="utf-8").write(s2)
    print(f, "css" if "BXCSS_START" in s2 else "-", "js" if "BXJS_START" in s2 else "-")
