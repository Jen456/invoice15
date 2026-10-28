"""Regenera el manual de clientes sin conexión a la aplicación ni base de datos."""
from pathlib import Path
from weasyprint import HTML

if __name__ == '__main__':
    carpeta = Path(__file__).resolve().parent
    salida = carpeta / 'Manual-de-uso-FacturaPorAqui.pdf'
    HTML(filename=str(carpeta / 'manual.html')).write_pdf(str(salida))
    print(salida)
