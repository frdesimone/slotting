import csv
from pathlib import Path

# Ajusta esta ruta si tu archivo está en otro lado
INPUT_FILE = Path("docs/Base de códigos - semestre jun-nov  (11-1-2026) - Std Logix.xlsx - Base cód. segun pedidos-final.csv")
OUTPUT_FILE = INPUT_FILE.with_name("codigos_con_flags.csv")

# Columnas a agregar
NEW_COLUMNS = ["Es Sensible", "Apto VLM"]
DEFAULT_VALUES = ["NO", "SI"]  # Por defecto: No sensible, Sí apto

def add_columns_to_csv():
    if not INPUT_FILE.exists():
        print(f"Error: No encuentro el archivo en {INPUT_FILE}")
        return

    print(f"Leyendo {INPUT_FILE}...")
    
    with open(INPUT_FILE, mode='r', encoding='utf-8-sig', newline='') as f_in, \
         open(OUTPUT_FILE, mode='w', encoding='utf-8-sig', newline='') as f_out:
        
        reader = csv.reader(f_in)
        writer = csv.writer(f_out)
        
        header_found = False
        header_index = -1
        
        for i, row in enumerate(reader):
            # Lógica para detectar la fila de encabezado real
            # Basado en tu archivo, empieza con "Código II" (a veces en la 2da columna si la A está vacía)
            # Limpiamos espacios y buscamos palabras clave
            row_clean = [c.strip() for c in row if c.strip()]
            
            if not header_found and "Código II" in row_clean:
                header_found = True
                header_index = i
                print(f"Encabezado encontrado en línea {i+1}")
                
                # Agregamos los nombres de las nuevas columnas al final de la fila actual
                # Nota: Si tu CSV tiene columnas vacías al final, esto las pondrá después.
                new_row = row + NEW_COLUMNS
                writer.writerow(new_row)
                continue
            
            if header_found:
                # Si ya pasamos el encabezado, es una fila de datos
                # Solo escribimos valores si la fila no está totalmente vacía
                if any(row):
                    new_row = row + DEFAULT_VALUES
                    writer.writerow(new_row)
                else:
                    # Mantener filas vacías intermedias si las hubiera (raro en datos, común en formato excel)
                    writer.writerow(row)
            else:
                # Si aún no encontramos el encabezado, copiamos las líneas de metadata tal cual
                writer.writerow(row)

    print(f"✅ Archivo creado exitosamente: {OUTPUT_FILE}")
    print("Ahora puedes editar este archivo en Excel para marcar manualmente los productos sensibles.")

if __name__ == "__main__":
    add_columns_to_csv()