"""Gráficas de los experimentos (requiere matplotlib). Lee los CSV y JSON de evidencias/."""
import csv
import json
import os

from experimentos.metricas import DIR_EVIDENCIAS

BASE, TACTICA, TACTICA2, FALLA, TEXTO = "#9AA0A6", "#1F5FAF", "#7FA7D9", "#F3D9D9", "#333333"


def _csv(ruta):
    with open(ruta, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _estilo(plt):
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.edgecolor": "#888888", "axes.titleweight": "bold",
                         "axes.titlesize": 11, "figure.dpi": 150})


def _etiquetas(ax, barras, fmt="{:.1f}"):
    for b in barras:
        ax.annotate(fmt.format(b.get_height()), (b.get_x() + b.get_width() / 2, b.get_height()),
                    ha="center", va="bottom", fontsize=9, color=TEXTO, xytext=(0, 2),
                    textcoords="offset points")


def generar():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    _estilo(plt)
    salida = os.path.join(DIR_EVIDENCIAS, "graficas")
    os.makedirs(salida, exist_ok=True)
    res = json.load(open(os.path.join(DIR_EVIDENCIAS, "resumen.json"), encoding="utf-8"))

    # ---- S1: línea base vs táctica ----
    b, t = res["s1"]["linea_base"], res["s1"]["con_tactica"]
    fig, ax = plt.subplots(figsize=(5.6, 3.2))
    metricas = ["Tarjetas clonadas\ndetectadas (%)", "Usos del clon\nbloqueados (%)"]
    vb = [b["pct_clonadas_detectadas"], b["pct_usos_clon_bloqueados"]]
    vt = [t["pct_clonadas_detectadas"], t["pct_usos_clon_bloqueados"]]
    x = range(len(metricas))
    _etiquetas(ax, ax.bar([i - 0.18 for i in x], vb, 0.36, color=BASE, label="Sin la táctica"))
    _etiquetas(ax, ax.bar([i + 0.18 for i in x], vt, 0.36, color=TACTICA, label="Con la táctica"))
    ax.set_xticks(list(x), metricas)
    ax.set_ylim(0, 110)
    ax.set_ylabel("%")
    ax.set_title("S1 – Ataque de 200 tarjetas clonadas (1000 usos)")
    ax.legend(frameon=False, loc="upper right", fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(salida, "s1_comparacion.png"))
    plt.close(fig)

    # ---- S1: barrido ----
    bar = res["s1"]["barrido"]
    fig, ax = plt.subplots(figsize=(6.4, 3.0))
    ax.plot([r["usos_clon"] for r in bar], [r["pct_detectadas"] for r in bar], "o-", color=TACTICA, lw=2)
    for r in bar:
        ax.annotate(f"{r['pct_detectadas']:.0f} %", (r["usos_clon"], r["pct_detectadas"]),
                    xytext=(0, 7), textcoords="offset points", ha="center", fontsize=9)
    ax.axhline(95, color="#C0392B", ls="--", lw=1)
    ax.text(1, 96.5, "meta de la ficha: 95 %", color="#C0392B", fontsize=8)
    ax.set_xlabel("Veces que el atacante usa la tarjeta clonada en una hora")
    ax.set_ylabel("Tarjetas clonadas detectadas (%)")
    ax.set_ylim(0, 110)
    ax.set_title("S1 – Detección según el uso que hace el atacante")
    fig.tight_layout()
    fig.savefig(os.path.join(salida, "s1_barrido.png"))
    plt.close(fig)

    # ---- D2: línea de tiempo ----
    fig, axes = plt.subplots(2, 1, figsize=(6.6, 5.0), sharex=True)
    for ax, sub, titulo in ((axes[0], "linea_base", "Sin la táctica (rechaza si no hay red)"),
                            (axes[1], "con_tactica", "Con la táctica (cola local + reintento)")):
        filas = _csv(os.path.join(DIR_EVIDENCIAS, "d2", sub, "toques.csv"))
        seg = {}
        for f in filas:
            s = int(float(f["t_s"]))
            ok = f["status"] == "200"
            a, r = seg.get(s, (0, 0))
            seg[s] = (a + ok, r + (not ok))
        xs = sorted(seg)
        ax.axvspan(30, 90, color=FALLA, lw=0)
        ax.bar(xs, [seg[s][0] for s in xs], 1.0, color=TACTICA, label="Aceptados")
        ax.bar(xs, [seg[s][1] for s in xs], 1.0, bottom=[seg[s][0] for s in xs], color="#C0392B",
               label="Rechazados")
        ax.set_ylabel("Toques / s")
        ax.set_ylim(0, 24)
        ax.set_title(titulo, loc="left")
        if sub == "con_tactica":
            m = _csv(os.path.join(DIR_EVIDENCIAS, "d2", sub, "muestras_cola.csv"))
            ax2 = ax.twinx()
            ax2.plot([float(r["t_s"]) for r in m], [int(r["en_cola"]) for r in m], color="#E08E0B", lw=1.8,
                     label="En cola")
            ax2.set_ylabel("Transacciones en cola", color="#E08E0B")
            ax2.spines["top"].set_visible(False)
            h1, l1 = ax.get_legend_handles_labels()
            h2, l2 = ax2.get_legend_handles_labels()
            ax2.set_ylim(0, 1500)
            manejadores = ax.get_legend_handles_labels()[0] + ax2.get_legend_handles_labels()[0]
        ax.text(60, 22, "enlace caído", ha="center", fontsize=8, color="#A33")
        ax.set_ylim(0, 25)
    axes[1].set_xlabel("Tiempo del experimento (s)")
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.legend(manejadores, [m.get_label() for m in manejadores], loc="lower center", ncol=3,
               frameon=False, fontsize=9)
    fig.savefig(os.path.join(salida, "d2_linea_tiempo.png"))
    plt.close(fig)

    # ---- Compromiso ----
    c = res["compromiso"]
    fig, ax = plt.subplots(figsize=(6.4, 3.3))
    grupos = ["p50", "p95", "p99"]
    conds = [("sin_deteccion", "Sin detección", BASE), ("con_deteccion", "Con detección (SQLite)", TACTICA),
             ("con_deteccion_memoria", "Con detección (solo memoria)", TACTICA2)]
    for k, (cond, nombre, color) in enumerate(conds):
        xs = [i + (k - 1) * 0.26 for i in range(3)]
        _etiquetas(ax, ax.bar(xs, [c[cond][f"{g}_ms"] for g in grupos], 0.26, color=color, label=nombre),
                   "{:.2f}")
    ax.set_xticks(range(3), ["p50", "p95", "p99"])
    ax.set_ylabel("Latencia de /validar (ms)")
    ax.set_title(f"Compromiso S vs. P – {c['tasa_rps']} validaciones/s, 3 repeticiones")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig(os.path.join(salida, "compromiso_latencia.png"))
    plt.close(fig)
    print(f"  gráficas en {salida}")


if __name__ == "__main__":
    generar()
