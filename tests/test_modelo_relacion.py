import unittest

import pandas as pd

from candidate.modelo_relacion import ModeloRelacionError, build_in_sistecredito


DESTS = [
    "Documento de identidad", "Nombre Completo", "Dirección Del Cliente", "Fecha Nacimiento",
    "Fecha Expedición", "Reportado a Centrales", "Crédito", "Fecha Creación del crédito", "Valor",
    "Número de cuotas vencidas", "Fecha de vencimiento", "Días en Mora", "Valor Mora", "Cargos Jurídico",
    "Saldo Total", "Telefono 1", "Telefono 2", "Telefono 3", "Telefono 4", "Almacén",
    "Municipio Almacén", "Dirección Almacén", "Teléfono Almacén", "Status", "Servicio", "Franja",
    "IN_PRIORIDAD", "Tipo de Documento", "In_Serviceid",
]
ORIGINS = [
    "Identificacion", "Upper;NombreCompleto", "DireccionResidencia", "FechaNacimiento", "FechaExpedicion",
    "EstadoCentrales", "Codigo", "FechaCreacion", "ValorCapital", "CuotasVencidas", "FechaMasVencida",
    "DiasMora", "SaldoMora", "Cargos Jurídico", "SaldoTotal", "", "", "", "", "Nombre;Almacen",
    "Nombre.1;Nombre", "Direccion", "PrimerTelefono", "CreditNumber", "", "", "", "Tipo Documento", "",
]
RULES = ["DIRECTO"] * 15 + ["REGLA_TELEFONOS"] * 4 + ["DIRECTO"] * 5 + ["DEFAULT", "REGLA_FRANJAS", "REGLA_PRIORIDAD", "DIRECTO", "DEFAULT"]


def current_model_rows():
    rows = []
    for index, (dest, origin, rule) in enumerate(zip(DESTS, ORIGINS, RULES), start=1):
        params = ""
        default = ""
        if rule == "REGLA_TELEFONOS":
            params = "cols=Celular,Celular2,Fijo,Fijo2;minlen=10;maxlen=11"
        elif rule == "REGLA_FRANJAS":
            params = "param=FranjaMora;col_dias=Días en Mora"
        elif rule == "REGLA_PRIORIDAD":
            params = "cols=Valor,Valor Mora,Cargos Jurídico;numeric=coerce;fillna=0;rank=dense;ascending=true"
        elif dest == "Servicio":
            default = "General"
        elif dest == "In_Serviceid":
            default = 1
        rows.append({
            "Sistema": "SinergIA", "ArchivoDestino": "IN_SISTECREDITO", "OrdenDestino": index,
            "ColumnaDestino": dest, "TipoDatoDestino": "Texto", "ColumnaOrigen": origin,
            "ValorPredeterminado": default, "TipoRegla": rule, "ParametrosRegla": params,
        })
    return rows


def current_parameter_rows():
    return [
        {"Parametro": "FranjaMoraPreset", "Preset": "", "Nombre": "Active", "Etiqueta": "Preset activo para FranjaMora", "Desde": "BASELINE", "Hasta": ""},
        {"Parametro": "FranjaMora", "Preset": "BASELINE", "Nombre": "Franja_00", "Etiqueta": "00. < 180", "Desde": 0, "Hasta": 179},
        {"Parametro": "FranjaMora", "Preset": "BASELINE", "Nombre": "Franja_01", "Etiqueta": "01. 180 a 359", "Desde": 180, "Hasta": 359},
        {"Parametro": "FranjaMora", "Preset": "BASELINE", "Nombre": "Franja_02", "Etiqueta": "02. 360 a 499", "Desde": 360, "Hasta": 499},
        {"Parametro": "FranjaMora", "Preset": "BASELINE", "Nombre": "Franja_03", "Etiqueta": "03. 500 a 1999", "Desde": 500, "Hasta": 1999},
        {"Parametro": "FranjaMora", "Preset": "BASELINE", "Nombre": "Franja_04", "Etiqueta": "04. >= 2000", "Desde": 2000, "Hasta": 99999},
    ]


def source_frame():
    return pd.DataFrame({
        "Identificacion": ["100", "200"], "NombreCompleto": ["Ana Pérez", "Luis Díaz"],
        "DireccionResidencia": ["  # 10-20  ", "CALLE 2"], "FechaNacimiento": ["01/01/1990", "02/02/1991"],
        "FechaExpedicion": ["01/01/2010", "02/02/2011"], "EstadoCentrales": [1, 0],
        "Codigo": ["C1", "C2"], "FechaCreacion": ["03/03/2020", "04/04/2021"],
        "ValorCapital": [100, 200], "CuotasVencidas": [1, 2], "FechaMasVencida": ["01/01/2026", "02/02/2026"],
        "DiasMora": [100, 400], "SaldoMora": [20, 30], "Cargos Jurídico": [5, 10], "SaldoTotal": [125, 240],
        "Celular": ["300 111 2233", "3001119999"], "Celular2": ["3001112233", ""],
        "Fijo": ["6044444444", "6045555555"], "Fijo2": ["6046666666", "6047777777"],
        "Almacen": ["A01", "A02"], "Nombre": ["Tienda Uno", "Tienda Dos"], "Nombre.1": ["Medellín", "Envigado"],
        "Direccion": ["Dir almacén 1", "Dir almacén 2"], "PrimerTelefono": ["6041111111", "6042222222"],
        "CreditNumber": ["S1", "S2"], "Tipo Documento": ["CC", "CE"],
    })


class ModeloRelacionBuilderTests(unittest.TestCase):
    def test_current_contract_builds_exact_29_columns_and_rules(self):
        out, evidence = build_in_sistecredito(source_frame(), model_rows=current_model_rows(), parameter_rows=current_parameter_rows())
        self.assertEqual(list(out.columns), DESTS)
        self.assertEqual(evidence.mapping_count, 29)
        self.assertEqual(out["Nombre Completo"].tolist(), ["ANA PÉREZ", "LUIS DÍAZ"])
        self.assertEqual(out["Almacén"].tolist(), ["Tienda Uno", "Tienda Dos"])
        self.assertEqual(out["Municipio Almacén"].tolist(), ["Medellín", "Envigado"])
        self.assertEqual(out["Servicio"].tolist(), ["General", "General"])
        self.assertEqual(out["In_Serviceid"].tolist(), [1, 1])
        self.assertEqual(out["Franja"].tolist(), ["00. < 180", "02. 360 a 499"])
        self.assertEqual(out["IN_PRIORIDAD"].tolist(), [1, 2])

    def test_phone_rule_deduplicates_but_does_not_inherit_mobile_only_hardcode(self):
        out, _ = build_in_sistecredito(source_frame(), model_rows=current_model_rows(), parameter_rows=current_parameter_rows())
        self.assertEqual(out.loc[0, "Telefono 1"], "3001112233")
        self.assertEqual(out.loc[0, "Telefono 2"], "6044444444")
        self.assertEqual(out.loc[0, "Telefono 3"], "6046666666")
        self.assertEqual(out.loc[0, "Telefono 4"], "")

    def test_builder_does_not_apply_limpiarcolumna_or_hidden_address_cleanup(self):
        rows = current_model_rows()
        for row in rows:
            row["LimpiarColumna"] = row["ColumnaDestino"] == "Dirección Del Cliente"
        out, _ = build_in_sistecredito(source_frame(), model_rows=rows, parameter_rows=current_parameter_rows())
        self.assertEqual(out.loc[0, "Dirección Del Cliente"], "  # 10-20  ")

    def test_literal_source_binding_is_fail_closed(self):
        source = source_frame().rename(columns={"Identificacion": "identificacion"})
        with self.assertRaisesRegex(ModeloRelacionError, "no literal DIRECTO source"):
            build_in_sistecredito(source, model_rows=current_model_rows(), parameter_rows=current_parameter_rows())

    def test_unsupported_rule_is_fail_closed(self):
        rows = current_model_rows()
        rows[0]["TipoRegla"] = "REGLA_FUZZY"
        with self.assertRaisesRegex(ModeloRelacionError, "unsupported TipoRegla"):
            build_in_sistecredito(source_frame(), model_rows=rows, parameter_rows=current_parameter_rows())

    def test_missing_or_malformed_priority_contract_is_fail_closed(self):
        rows = current_model_rows()
        rows[26]["ParametrosRegla"] = "cols=Valor,Valor Mora,Cargos Jurídico;numeric=coerce;rank=dense;ascending=true"
        with self.assertRaisesRegex(ModeloRelacionError, "missing ParametrosRegla keys"):
            build_in_sistecredito(source_frame(), model_rows=rows, parameter_rows=current_parameter_rows())

    def test_duplicate_order_is_fail_closed(self):
        rows = current_model_rows()
        rows[1]["OrdenDestino"] = 1
        with self.assertRaisesRegex(ModeloRelacionError, "OrdenDestino must be exactly"):
            build_in_sistecredito(source_frame(), model_rows=rows, parameter_rows=current_parameter_rows())

    def test_missing_configured_phone_source_is_fail_closed(self):
        with self.assertRaisesRegex(ModeloRelacionError, "required source column missing"):
            build_in_sistecredito(source_frame().drop(columns=["Fijo2"]), model_rows=current_model_rows(), parameter_rows=current_parameter_rows())

    def test_overlapping_franja_ranges_are_fail_closed(self):
        params = current_parameter_rows()
        params[2]["Desde"] = 170
        with self.assertRaisesRegex(ModeloRelacionError, "overlapping ranges"):
            build_in_sistecredito(source_frame(), model_rows=current_model_rows(), parameter_rows=params)


if __name__ == "__main__":
    unittest.main()
