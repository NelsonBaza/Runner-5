#ESTE CÓDIGO OPTIMIZA PROGRESIVAMENTE LOS PARÁMETROS POR TIPO DE VEHICULO.
#Optimiza automoviles según la cantidad de iteraciones, luego con los parámetros encontrados optimiza motocicletas y finalmente camiones.
#Adicionalmente este código genera perturbaciones para escapar de minimos locales.

from __future__ import absolute_import
from __future__ import print_function
import os
import sys
import pandas as pd
import numpy as np
from sumolib import checkBinary
import traci
import xlsxwriter
import subprocess
from tabulate import tabulate
import xml.etree.ElementTree as ET
import matplotlib.pyplot as plt
from scipy.optimize import fmin_cobyla

# Verificar si SUMO está configurado correctamente
if 'SUMO_HOME' in os.environ:
    tools = os.path.join(os.environ['SUMO_HOME'], 'tools')
    sys.path.append(tools)
else:
    sys.exit("Por favor, declara la variable de entorno 'SUMO_HOME'")

# Ruta de la configuración de SUMO
CONFIG_FILE = "config.sumocfg"
DUACONFIG_FILE = "duaconfig.duarcfg"
ROUTES_FILE = "rutas.xml"
VTYPE_FILE = "vtype.xml"

#  Archivo de datos observados
observed_excel = "flujos_observados.xlsx"

# Factores iniciales de variación (% del valor actual)
variation_factors = {
    "accel": 0.5,   # 10% del valor actual
    "decel": 0.5,   # 10% del valor actual
    "sigma": 0.3,  # 10% del valor actual
    "tau": 0.2,    # 10% del valor actual
    "minGap": 0.5,  # 10% del valor actual
    "lcStrategic": 0.3,   
    "lcCooperative": 0.3, 
    "lcSpeedGain": 0.3,  
}

# Topes mínimos y máximos de los parámetros
parameter_bounds = {
    "automovil": {
        "accel": (0.5, 5.0),
        "decel": (1.0, 9.0),
        "sigma": (0.0, 1.0),
        "tau": (0.5, 2.5),
        "minGap": (1.0, 3.0),
        "lcStrategic": [0.0, 1.0],   
        "lcCooperative": [0.0, 1.0], 
        "lcSpeedGain": [0.0, 1.0],  
    },
    "motocicleta": {
        "accel": (1.0, 6.0),
        "decel": (1.5, 10.0),
        "sigma": (0.1, 1.0),
        "tau": (0.3, 1.5),
        "minGap": (0.5, 2.0),
        "lcStrategic": [0.2, 0.8],   
        "lcCooperative": [0.0, 0.9], 
        "lcSpeedGain": [0.0, 0.9], 
    },
    "camion": {
        "accel": (0.3, 2.0),
        "decel": (0.5, 5.0),
        "sigma": (0.0, 0.5),
        "tau": (1.0, 3.0),
        "minGap": (2.0, 5.0),
        "lcStrategic": [0.2, 0.7],   
        "lcCooperative": [0.0, 0.8], 
        "lcSpeedGain": [0.0, 0.7], 
    }
}

# Función para cargar parámetros iniciales desde el archivo vtype.xml
def load_initial_vtype(vtype_file):
    tree = ET.parse(vtype_file)
    root = tree.getroot()

    initial_params = {}
    for vtype in root.findall("vType"):
        vtype_id = vtype.get("id")
        initial_params[vtype_id] = {
            "accel": float(vtype.get("accel")),
            "decel": float(vtype.get("decel")),
            "sigma": float(vtype.get("sigma")),
            "tau": float(vtype.get("tau")),
            "minGap": float(vtype.get("minGap")),
            "lcStrategic": float(vtype.get("lcStrategic")),
            "lcCooperative": float(vtype.get("lcCooperative")),
            "lcSpeedGain": float(vtype.get("lcSpeedGain")),
            "other_params": {key: vtype.get(key) for key in vtype.keys() if key not in ["id", "accel", "decel", "sigma", "tau", "minGap", "lcStrategic", "lcCooperative", "lcSpeedGain"]}
        }
    print("Parámetros iniciales cargados correctamente.")
    print(initial_params)
    return initial_params

# Función para obtener parámetros iniciales de un tipo de vehículo específico
def get_initial_params(vehicle_type):
    return [
        initial_vtype_params[vehicle_type]["accel"],
        initial_vtype_params[vehicle_type]["decel"],
        initial_vtype_params[vehicle_type]["sigma"],
        initial_vtype_params[vehicle_type]["tau"],
        initial_vtype_params[vehicle_type]["minGap"],
        initial_vtype_params[vehicle_type]["lcStrategic"],
        initial_vtype_params[vehicle_type]["lcCooperative"],
        initial_vtype_params[vehicle_type]["lcSpeedGain"]
    ]

# Cargar parámetros iniciales desde el archivo vtype.xml
initial_vtype_params = load_initial_vtype(VTYPE_FILE)

# Cargar datos observados desde el archivo Excel
observed_data = pd.read_excel(observed_excel)  # Cargar datos observados
observed_data.fillna(0, inplace=True) # Reemplazar valores nulos con cero


# Actualizar el archivo vtype.xml con los nuevos parámetros
def update_vtype_file(vtype_file, updated_params):
    # Cargar todos los vehículos desde el archivo vtype.xml
    tree = ET.parse(vtype_file)
    root = tree.getroot()

    for vtype in root.findall("vType"):
        vtype_id = vtype.get("id")
        
        # Verificar si el vehículo está en los parámetros actualizados
        if vtype_id in updated_params:
            vtype.set("accel", str(updated_params[vtype_id]["accel"]))
            vtype.set("decel", str(updated_params[vtype_id]["decel"]))
            vtype.set("sigma", str(updated_params[vtype_id]["sigma"]))
            vtype.set("tau", str(updated_params[vtype_id]["tau"]))
            vtype.set("minGap", str(updated_params[vtype_id]["minGap"]))
            vtype.set("lcStrategic", str(updated_params[vtype_id]["lcStrategic"]))
            vtype.set("lcCooperative", str(updated_params[vtype_id]["lcCooperative"]))
            vtype.set("lcSpeedGain", str(updated_params[vtype_id]["lcSpeedGain"]))
            
            # Mantener otros parámetros originales
            for key, val in updated_params[vtype_id].get("other_params", {}).items():
                vtype.set(key, val)
        else:
            print(f"Advertencia: No se encontraron parámetros para {vtype_id}, se mantienen los valores originales.")

    # Guardar el archivo actualizado
    tree.write(vtype_file)
    print(f"Archivo {vtype_file} actualizado correctamente con los nuevos parámetros.")

# Función para generar un nuevo archivo de rutas con DUAROUTER
def generate_routes(duaconfig_file, routes_file):
    try:
        subprocess.run([
            checkBinary("duarouter"), "-c", duaconfig_file, "--output-file", routes_file
        ], check=True)
        print(f"Archivo de rutas generado: {routes_file}")
    except subprocess.CalledProcessError as e:
        print(f"Error al generar el archivo de rutas: {e}")
        sys.exit(1)

# Función para actualizar el archivo config.sumocfg con el nuevo archivo de rutas
def update_config_file(config_file, routes_file):
    with open(config_file, 'r') as f:
        config_data = f.read()
    
    if "rutas.xml" in config_data:
        config_data = config_data.replace("rutas.xml", os.path.basename(routes_file))
        print(f"Archivo de configuración actualizado con {routes_file}")

    with open(config_file, 'w') as f:
        f.write(config_data)

# Ejecutar simulación y recoger datos directamente de los detectores
def run_simulation(config_file, max_time=3600):
    traci.start([checkBinary("sumo"),"-c", config_file ])
    print("Simulación iniciada con el archivo de configuración:", config_file)

    unique_vehicle_ids = {}
    simulation_time = 0  # Tiempo acumulado en la simulación (en segundos)

    while simulation_time < max_time:
        traci.simulationStep()
        simulation_time += traci.simulation.getDeltaT()  # Obtén el paso temporal configurado en la simulación
        
        for detector_id in traci.inductionloop.getIDList():
            veh_ids = traci.inductionloop.getLastStepVehicleIDs(detector_id)

            # Mantener el historial de vehículos detectados durante toda la simulación
            if detector_id not in unique_vehicle_ids:
                unique_vehicle_ids[detector_id] = set()
            # Agregar vehículos nuevos al conjunto
            unique_vehicle_ids[detector_id].update(veh_ids)

    # Crear una estructura para agrupar los datos por intersección
    intersection_data = {}

    # Contar vehículos únicos por detector al final de la simulación
    for detector_id, veh_set in unique_vehicle_ids.items():
        intersection = extract_intersection(detector_id)  # Obtener la intersección del detector
    
        # Sumar los datos de los detectores de la misma intersección
        if intersection not in intersection_data:
            intersection_data[intersection] = set()
        intersection_data[intersection].update(veh_set)

    # Conteo total por intersección
    intersection_flows = {k: len(v) for k, v in intersection_data.items()}

    # Retornar los datos consolidados por intersección
    traci.close()

    # Crear tabla para imprimir
    table_data = [[intersection, count] for intersection, count in intersection_flows.items()]
    print(tabulate(table_data, headers=["Intersección", "Cantidad de Vehículos"], tablefmt="grid"))

    # Retornar los flujos
    return intersection_flows

# Función para extraer la intersección a partir del nombre del detector
def extract_intersection(detector_id):
    """
    Extrae la parte del nombre del detector antes del guion bajo y número
    para identificar la intersección general.
    """
    parts = detector_id.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():  # Si el último elemento es un número
        return parts[0]  # Devuelve el prefijo sin el número
    return detector_id  # Mantiene detectores sin sufijo de carril

# Función principal para comparar datos simulados vs observados
def compare_observed_vs_simulated(simulated, observed):
    # Reinicia el índice y asegura que los datos observados tengan la columna "Detector_ID"
    observed = observed.reset_index()

    # Convierte los datos simulados en un DataFrame
    simulated_df = pd.DataFrame(list(simulated.items()), columns=["Interseccion", "Flujo_Simulado"])

    # Extraer la intersección de cada detector en ambos conjuntos de datos
    observed["Interseccion"] = observed["Detector_ID"].apply(extract_intersection)
    #simulated_df["Interseccion"] = simulated_df["Detector_ID"].apply(extract_intersection)

    # Realizar el merge a nivel de intersección
    merged = pd.merge(observed, simulated_df, on="Interseccion", how="inner")

    # Agrupar por intersección y sumar flujos
    grouped = merged.groupby("Interseccion", as_index=False).agg({
        "Flujo_Observado": "sum",
        "Flujo_Simulado": "sum"
    })

    # Manejo de valores nulos
    grouped["Flujo_Observado"] = pd.to_numeric(grouped["Flujo_Observado"], errors="coerce").fillna(0)
    grouped["Flujo_Simulado"] = pd.to_numeric(grouped["Flujo_Simulado"], errors="coerce").fillna(0)

    # Cálculo del GEH
    grouped["GEH"] = np.where(
        (grouped["Flujo_Observado"] + grouped["Flujo_Simulado"]) > 0,
        np.sqrt(2 * (grouped["Flujo_Simulado"] - grouped["Flujo_Observado"])**2 /
                (grouped["Flujo_Simulado"] + grouped["Flujo_Observado"])),
        0
    )

    # Exportar datos agrupados por intersección a un archivo Excel
    grouped.to_excel("flujos_agrupados.xlsx", index=False)
    print("Datos agrupados por intersección exportados a 'flujos_agrupados.xlsx'")
    return grouped

# Calcular el GEH entre valores simulados y observados
def calculate_geh(observed, simulated):
    geh = np.sqrt(2 * (simulated - observed)**2 / (simulated + observed))
    return geh

# Función para reducir la variación según la iteración actual
def adapt_variation(base_variation, iteration, max_iterations):
    """
    Reduce la magnitud de la variación a medida que se avanza en las iteraciones.
    :param base_variation: Tasa inicial de variación
    :param iteration: Iteración actual
    :param max_iterations: Número máximo de iteraciones
    :return: Tasa de variación ajustada
    """
    factor = 1 - np.sqrt(iteration / max_iterations)   # Disminuye con la iteración
    return base_variation * max(0.4, factor)   # No permite que la variación sea menor al 40%


# Historial de parametros
parameter_history = {
    "automovil": [],
    "motocicleta": [],
    "camion": []
}

# Contador de iteraciones para el titulo de cada iteración
iteration_count = 0

# Lista global para almacenar datos de cantidad de detectores en cada rango de GEH para cada iteración
iteration_summary = []  # Lista global para almacenar datos de cada iteración

# Función para exportar el resumen acumulado de GEH a un archivo Excel
def export_geh_summary_to_excel(iteration_summary, output_file="resumen_geh.xlsx"):
    df_summary = pd.DataFrame(iteration_summary)
    df_summary.to_excel(output_file, index=False, sheet_name="Resumen GEH")
    print(f"\nResumen acumulado de GEH guardado en '{output_file}'")

# -------------------------- FUNCIÓN OBJETIVO PRINCIPAL DE OPTIMIZACIÓN ------------------------------
def objective_function(params, vtype_file, config_file, duaconfig_file, routes_file, observed_data, vehicle_type):
    global iteration_count
    iteration_count += 1

    # Imprimir encabezado de la iteración
    print(f"\n{'='*40}")
    print(f"OPTIMIZANDO {vehicle_type.upper()} - ITERACIÓN N°{iteration_count}")
    print(f"{'='*40}\n")

    # Calcular tasas adaptativas para esta iteración
    adapted_variation_factors = {
        key: adapt_variation(value, iteration_count, max_iterations=5)
        for key, value in variation_factors.items()
    }

    # Actualizar parámetros solo para el tipo de vehículo específico
    bounds = parameter_bounds[vehicle_type]
    # Actualizar parámetros solo para el tipo de vehículo específico, aplicando las tasas adaptativas
    updated_params = {
        vehicle_type: {
            "accel": max(bounds["accel"][0], min(bounds["accel"][1], params[0] * (1 + adapted_variation_factors["accel"]))),
            "decel": max(bounds["decel"][0], min(bounds["decel"][1], params[1] * (1 + adapted_variation_factors["decel"]))),
            "sigma": max(bounds["sigma"][0], min(bounds["sigma"][1], params[2] * (1 + adapted_variation_factors["sigma"]))),
            "tau": max(bounds["tau"][0], min(bounds["tau"][1], params[3] * (1 + adapted_variation_factors["tau"]))),
            "minGap": max(bounds["minGap"][0], min(bounds["minGap"][1], params[4] * (1 + adapted_variation_factors["minGap"]))),
            "lcStrategic": max(bounds["lcStrategic"][0], min(bounds["lcStrategic"][1], params[5] * (1 + adapted_variation_factors["lcStrategic"]))),
            "lcCooperative": max(bounds["lcCooperative"][0], min(bounds["lcCooperative"][1], params[6] * (1 + adapted_variation_factors["lcCooperative"]))),
            "lcSpeedGain": max(bounds["lcSpeedGain"][0], min(bounds["lcSpeedGain"][1], params[7] * (1 + adapted_variation_factors["lcSpeedGain"]))),            
            "other_params": initial_vtype_params[vehicle_type]["other_params"]
        }
    }

    # Actualizar historial de parámetros para el tipo de vehículo actual
    if vehicle_type not in parameter_history:
        parameter_history[vehicle_type] = []

    parameter_history[vehicle_type].append({
        "Iteración": iteration_count,
        "accel": updated_params[vehicle_type]["accel"],
        "decel": updated_params[vehicle_type]["decel"],
        "sigma": updated_params[vehicle_type]["sigma"],
        "tau": updated_params[vehicle_type]["tau"],
        "minGap": updated_params[vehicle_type]["minGap"],
        "lcStrategic": updated_params[vehicle_type]["lcStrategic"],
        "lcCooperative": updated_params[vehicle_type]["lcCooperative"],
        "lcSpeedGain": updated_params[vehicle_type]["lcSpeedGain"]
    })

    # Crear tabla para impresión
    history_table = []
    
    # Obtener el historial del vehículo actual
    history = parameter_history.get(vehicle_type, [])

    if not history:
        print(f"No hay datos disponibles para {vehicle_type.upper()}.")
    else:
        history_table = [
            {
                "Iteración": entry.get("Iteración", "N/A"),
                "accel": entry.get("accel", "N/A"),
                "decel": entry.get("decel", "N/A"),
                "sigma": entry.get("sigma", "N/A"),
                "tau": entry.get("tau", "N/A"),
                "minGap": entry.get("minGap", "N/A"),
                "lcStrategic": entry.get("lcStrategic", "N/A"),
                "lcCooperative": entry.get("lcCooperative", "N/A"),
                "lcSpeedGain": entry.get("lcSpeedGain", "N/A")
            }
            for entry in history
        ]

        print(f"\nHistorial de parámetros por iteración para: {vehicle_type.upper()}")
        print(tabulate(history_table, headers="keys", tablefmt="grid", showindex=False))

    # Actualizar el archivo de tipos de vehículos (vtype.xml)
    update_vtype_file(vtype_file, updated_params)

    # Generar nuevas rutas y ejecutar simulación
    generate_routes(duaconfig_file, routes_file)
    update_config_file(config_file, routes_file)
    
    # Ejecutar simulación y obtener los flujos simulados por intersección
    simulated_data = run_simulation(config_file)

    # Comparar los flujos simulados (intersection_flows) con los observados
    comparison_table = compare_observed_vs_simulated(simulated_data, observed_data)
    
    # Calcular el GEH promedio
    geh_avg = comparison_table["GEH"].mean()

    global previous_geh, stagnation_count

    # Comprobar si hay estancamiento en la mejora del GEH
    if abs(previous_geh - geh_avg) < restart_threshold:
        stagnation_count += 1
    else:
        stagnation_count = 0  # Reiniciar contador si hubo mejora

    previous_geh = geh_avg  # Actualizar valor de GEH previo    

    if stagnation_count >= stagnation_limit:
        print(f"\nEstancamiento detectado en {vehicle.upper()}, reiniciando con perturbaciones aleatorias...")

    else:
        initial_params = get_initial_params(vehicle)

        # Introducir perturbaciones aleatorias en los parámetros actuales
        perturbation_factor = 0.5  # Factor de perturbación (50% del valor actual)
        perturbed_params = [
            param * (1 + perturbation_factor * (2 * np.random.rand() - 1))  # Perturbación en [-10%, +10%]
            for param in initial_params
        ]

        initial_params = perturbed_params  # Aplicar los nuevos valores como punto de inicio
        stagnation_count = 0  # Reiniciar el contador de estancamiento

    # Imprimir la tabla de comparación Observado vs Simulado con GEH
    print("\nTabla de comparación Observado vs Simulado:")
    print(tabulate(comparison_table[["Interseccion", "Flujo_Observado", "Flujo_Simulado", "GEH"]],
               headers="keys", tablefmt="grid", showindex=False))


    # Imprimir el valor promedio del GEH en la iteración actual
    print(f"\nValor promedio del GEH en la iteración {iteration_count}: {geh_avg:.2f}")

    # Contar detectores según los rangos de GEH
    detectores_geh_menor_5 = (comparison_table["GEH"] < 5).sum()
    detectores_geh_entre_5_10 = ((comparison_table["GEH"] >= 5) & (comparison_table["GEH"] < 10)).sum()
    detectores_geh_mayor_10 = (comparison_table["GEH"] >= 10).sum()

    # Crear la tabla de resultados por iteración
    iteration_results = {
        "Iteración": iteration_count,
        "Detectores con GEH < 5": detectores_geh_menor_5,
        "Detectores con 5 < GEH < 10": detectores_geh_entre_5_10,
        "Detectores con GEH > 10": detectores_geh_mayor_10,
        "GEH Promedio": round(geh_avg, 2)  # Redondeamos a 2 decimales
    }

    # Agregar los resultados de la iteración a la lista global
    iteration_summary.append(iteration_results)

    # Imprimir la tabla acumulativa de todas las iteraciones
    print("\nResumen acumulado de GEH por Iteración:")
    print(tabulate(iteration_summary, headers="keys", tablefmt="grid"))

    # Imprimir la tabla de historial de parámetros
    print(f"\nValor promedio del GEH para {vehicle_type.upper()} en la iteración {iteration_count}: {geh_avg:.2f}")

    return geh_avg  # Retorna el valor del GEH promedio como métrica de optimización

# Función para obtener restricciones específicas de un tipo de vehículo
def get_constraints(vehicle_type):
    bounds = parameter_bounds[vehicle_type]
    return [
        lambda p, *args: p[0] - bounds["accel"][0],  # accel min
        lambda p, *args: bounds["accel"][1] - p[0],  # accel max
        lambda p, *args: p[1] - bounds["decel"][0],  # decel min
        lambda p, *args: bounds["decel"][1] - p[1],  # decel max
        lambda p, *args: p[2] - bounds["sigma"][0],  # sigma min
        lambda p, *args: bounds["sigma"][1] - p[2],  # sigma max
        lambda p, *args: p[3] - bounds["tau"][0],    # tau min
        lambda p, *args: bounds["tau"][1] - p[3],    # tau max
        lambda p, *args: p[4] - bounds["minGap"][0], # minGap min
        lambda p, *args: bounds["minGap"][1] - p[4], # minGap max
        lambda p, *args: p[5] - bounds["lcStrategic"][0],  # lcStrategic min
        lambda p, *args: bounds["lcStrategic"][1] - p[5],  # lcStrategic max
        lambda p, *args: p[6] - bounds["lcCooperative"][0],  # lcCooperative min
        lambda p, *args: bounds["lcCooperative"][1] - p[6],  # lcCooperative max
        lambda p, *args: p[7] - bounds["lcSpeedGain"][0],  # lcSpeedGain min
        lambda p, *args: bounds["lcSpeedGain"][1] - p[7],  # lcSpeedGain max
    ]


# Función para exportar el historial de parámetros a un archivo Excel
def export_parameter_history_to_excel(parameter_history, output_file="historial_parametros.xlsx"):
    with pd.ExcelWriter(output_file, engine='xlsxwriter') as writer:
        for vtype_id, history in parameter_history.items():
            df = pd.DataFrame(history)
            df.to_excel(writer, sheet_name=vtype_id, index=False)
    print(f"\nHistorial de parámetros guardado en '{output_file}'")

# Parámetros para la estrategia de reinicio
restart_threshold = 0.01  # Umbral de mejora mínima para reiniciar
stagnation_limit = 10     # Número de iteraciones sin mejora para reiniciar
previous_geh = float('inf')  # Inicializar con un valor alto
stagnation_count = 0        # Contador de iteraciones sin mejora

# Lista de tipos de vehículos a optimizar individualmente
vehicle_types = ["automovil", "motocicleta", "camion"]

for vehicle in vehicle_types:
    print(f"\nIniciando optimización para: {vehicle.upper()}")

    # Usar los parámetros perturbados si se ha producido un reinicio, de lo contrario, obtener los parámetros iniciales
    if stagnation_count >= stagnation_limit:
        print(f"\nUsando parámetros perturbados para {vehicle.upper()}")
    else:
        initial_params = get_initial_params(vehicle)    

    # Obtener restricciones específicas para este vehículo
    constraints = get_constraints(vehicle)

    # Llamar a la función de optimización
    optimized_params = fmin_cobyla(
        objective_function,
        initial_params,  
        constraints,
        args=(VTYPE_FILE, CONFIG_FILE, DUACONFIG_FILE, ROUTES_FILE, observed_data, vehicle),
        maxfun=1500,  
        rhoend=1e-5   # Especifica la precisión mínima con la que se busca una solución óptima.
    )

    print(f"\nParámetros óptimos para {vehicle.upper()}: {optimized_params}")


# Llamar a la función después de completar la optimización
export_parameter_history_to_excel(parameter_history)

# Exportar resumen de GEH después de la optimización
export_geh_summary_to_excel(iteration_summary)
print("\nLos resultados han sido guardados en archivos Excel.")

def plot_geh_evolution(iteration_summary):
    """Genera gráficos de evolución del GEH por iteración."""
    iterations = [entry["Iteración"] for entry in iteration_summary]
    geh_average = [entry["GEH Promedio"] for entry in iteration_summary]
    geh_below_5 = [entry["Detectores con GEH < 5"] for entry in iteration_summary]
    geh_between_5_10 = [entry["Detectores con 5 < GEH < 10"] for entry in iteration_summary]
    geh_above_10 = [entry["Detectores con GEH > 10"] for entry in iteration_summary]

    plt.figure(figsize=(12, 6))

    # GEH promedio por iteración
    plt.plot(iterations, geh_average, marker='o', label="GEH Promedio", linewidth=2)

    # Número de detectores en cada rango de GEH
    plt.plot(iterations, geh_below_5, marker='s', label="Detectores GEH < 5", linestyle='--')
    plt.plot(iterations, geh_between_5_10, marker='^', label="Detectores 5 < GEH < 10", linestyle='-.')
    plt.plot(iterations, geh_above_10, marker='x', label="Detectores GEH > 10", linestyle=':')

    # Configuración del gráfico
    plt.title("Evolución del GEH por Iteración")
    plt.xlabel("Iteración")
    plt.ylabel("Número de Detectores / GEH Promedio")
    plt.legend()
    plt.grid(True)
    plt.show()

# Llamada a la función para graficar los resultados
plot_geh_evolution(iteration_summary)
plt.savefig("evolucion_geh.png")