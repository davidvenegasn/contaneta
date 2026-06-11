"""SAT catalogs — subset used in the PDF representation."""

FORMA_PAGO = {
    "01": "Efectivo",
    "02": "Cheque nominativo",
    "03": "Transferencia",
    "04": "Tarjeta de crédito",
    "05": "Monedero electrónico",
    "06": "Dinero electrónico",
    "08": "Vales de despensa",
    "12": "Dación en pago",
    "13": "Pago por subrogación",
    "14": "Pago por consignación",
    "15": "Condonación",
    "17": "Compensación",
    "23": "Novación",
    "24": "Confusión",
    "25": "Remisión de deuda",
    "26": "Prescripción o caducidad",
    "27": "A satisfacción del acreedor",
    "28": "Tarjeta de débito",
    "29": "Tarjeta de servicios",
    "30": "Aplicación de anticipos",
    "31": "Intermediario pagos",
    "99": "Por definir",
}

METODO_PAGO = {
    "PUE": "Una sola exhibición",
    "PPD": "Pago en parcialidades o diferido",
}

USO_CFDI = {
    "G01": "Adquisición de mercancías",
    "G02": "Devoluciones, descuentos o bonificaciones",
    "G03": "Gastos en general",
    "I01": "Construcciones",
    "I02": "Mobiliario y equipo de oficina",
    "I03": "Equipo de transporte",
    "I04": "Equipo de cómputo",
    "I05": "Dados, troqueles, herramientas",
    "I06": "Comunicaciones telefónicas",
    "I07": "Comunicaciones satelitales",
    "I08": "Otra maquinaria y equipo",
    "D01": "Honorarios médicos, dentales y hospitalarios",
    "D02": "Gastos médicos por incapacidad o discapacidad",
    "D03": "Gastos funerarios",
    "D04": "Donativos",
    "D05": "Intereses reales (créditos hipotecarios)",
    "D06": "Aportaciones voluntarias al SAR",
    "D07": "Primas por seguros de gastos médicos",
    "D08": "Gastos de transportación escolar",
    "D09": "Depósitos en cuentas para el ahorro",
    "D10": "Pagos por servicios educativos",
    "S01": "Sin efectos fiscales",
    "CP01": "Pagos",
    "CN01": "Nómina",
}

REGIMEN_FISCAL = {
    "601": "General de Ley Personas Morales",
    "603": "Personas Morales con Fines no Lucrativos",
    "605": "Sueldos y Salarios",
    "606": "Arrendamiento",
    "607": "Régimen de Enajenación o Adquisición de Bienes",
    "608": "Demás ingresos",
    "610": "Residentes en el Extranjero sin EP",
    "611": "Ingresos por Dividendos",
    "612": "Personas Físicas con Actividades Empresariales y Profesionales",
    "614": "Ingresos por intereses",
    "615": "Régimen de los ingresos por obtención de premios",
    "616": "Sin obligaciones fiscales",
    "620": "Sociedades Cooperativas de Producción",
    "621": "Incorporación Fiscal",
    "622": "Actividades Agrícolas, Ganaderas, Silvícolas y Pesqueras",
    "623": "Opcional para Grupos de Sociedades",
    "624": "Coordinados",
    "625": "Plataformas Tecnológicas",
    "626": "RESICO",
    "628": "Hidrocarburos",
    "629": "Regímenes Fiscales Preferentes",
    "630": "Enajenación de acciones en bolsa",
}

TIPO_COMPROBANTE = {
    "I": "Ingreso",
    "E": "Egreso",
    "T": "Traslado",
    "N": "Nómina",
    "P": "Pago",
}

CLAVE_UNIDAD = {
    "E48": "Unidad de servicio",
    "ACT": "Actividad",
    "H87": "Pieza",
    "EA": "Cada uno",
    "KGM": "Kilogramo",
    "MTR": "Metro",
    "LTR": "Litro",
    "HUR": "Hora",
    "DAY": "Día",
    "MON": "Mes",
}


def label(catalog: dict, code: str, default: str = "") -> str:
    """Get human label for a SAT code; return default (or code) if missing."""
    if not code:
        return default
    code = str(code).strip().upper()
    return catalog.get(code, default or code)
