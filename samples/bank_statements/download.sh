#!/usr/bin/env bash
# Descarga los PDFs públicos de muestra desde portales de transparencia mexicanos.
# Fuentes documentadas en README.md.
# Uso: bash samples/bank_statements/download.sh

set -e

DEST="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$DEST"/{bbva,banorte,santander,citibanamex,hsbc,scotiabank,banbajio,inbursa,azteca,banregio,mifel}

dl() {
  local out="$1"; local url="$2"
  if [[ -f "$out" ]] && [[ $(wc -c < "$out") -gt 10000 ]]; then
    echo "  skip $out (ya existe)"
  else
    curl -sS -L -o "$out" "$url" && echo "  ✓ $out"
  fi
}

echo "BBVA…"
dl "$DEST/bbva/bbva_jalisco_2022_01.pdf" "https://transparencia.info.jalisco.gob.mx/sites/default/files/8FVX-2022-01-Estado%20de%20cuenta.pdf"
dl "$DEST/bbva/bbva_jalisco_2021_05.pdf" "https://transparencia.info.jalisco.gob.mx/sites/default/files/ESTADOS%20DE%20CTA%20BBVA%20MAYO%202021.pdf"
dl "$DEST/bbva/bbva_coahuila_2016.pdf" "https://www.sefincoahuila.gob.mx/contenido/docs/cuentapublica/2016/07%20Caratulas%20Bancarias%2002/BBVA%20BANCOMER%202016/MAS%20DE%201000/0446533647/ESTADO%20DE%20CUENTA.pdf"
dl "$DEST/bbva/bbva_fondos_inversion.pdf" "https://www.bbva.mx/content/dam/public-web/mexico/documents/empresas/fondos/home-fondos-de-inversion/do_4_Estado_de_cuenta_tcm1344-627429.pdf"

echo "Banorte…"
dl "$DEST/banorte/banorte_guadalajara_2024.pdf" "https://transparencia.guadalajara.gob.mx/sites/default/files/8176-BANORTE-2024.pdf"
dl "$DEST/banorte/banorte_seapal_2024_04.pdf" "https://www.seapal.gob.mx/docs/transparencia_opd/Banorte-Abr-2024.pdf"
dl "$DEST/banorte/banorte_difzapopan_2024_11.pdf" "https://t.difzapopan.gob.mx/8/V/x/2024/11.-%20Estados%20de%20cuenta%20bancarios%20Noviembre%202024/BANORTE%20CONCENTRADORA%201550%20NOVIEMBRE%202024.pdf"

echo "Santander…"
dl "$DEST/santander/santander_pv_2024_05.pdf" "https://transparencia.puertovallarta.gob.mx/transparenciaY/art8/V/estados-cuenta/2024/SANTANDER/05.MAY/SANTANDER%20MAYO%202024%20CTA%2065505885624.pdf"
dl "$DEST/santander/santander_pv_2025_03.pdf" "https://transparencia.puertovallarta.gob.mx/transparenciaY/art8/V/estados-cuenta/2025/SANTANDER/03.MAR/65-50899771-4.pdf"
dl "$DEST/santander/santander_guadalajara_2021_08.pdf" "https://transparencia.guadalajara.gob.mx/sites/default/files/EstadoCuentaBancarioSantanderAgosto21.pdf"

echo "Citibanamex…"
dl "$DEST/citibanamex/citibanamex_pv_2024_02.pdf" "https://transparencia.puertovallarta.gob.mx/transparenciaY/art8/V/estados-cuenta/2024/banamex/02.FEB/CITIBANAMEX%20FEBRERO%202024%20002375701454068604.pdf"
dl "$DEST/citibanamex/citibanamex_seapal_2026_02.pdf" "https://www.seapal.gob.mx/docs/transparencia_opd/Banamex-feb.pdf"
dl "$DEST/citibanamex/citibanamex_pv_2023_04.pdf" "https://transparencia.puertovallarta.gob.mx/transparenciaY/art8/V/estados-cuenta/2023/marzo-abril/CUENTA%207005%206913430%20BANAMEX%20Abril.pdf"

echo "HSBC…"
dl "$DEST/hsbc/hsbc_triejal_2019_08.pdf" "https://www.triejal.gob.mx/transparencia/banco/HSBCSP-INST_ago2019.pdf"
dl "$DEST/hsbc/hsbc_seapal.pdf" "https://www.seapal.gob.mx/docs/transparencia_opd/HSBC.pdf"
dl "$DEST/hsbc/hsbc_tlaquepaque_2013_05.pdf" "https://transparencia.tlaquepaque.gob.mx/wp-content/uploads/2016/01/Estado-de-cuenta-bancario-HSBC-Mayo-2013.pdf.pdf"

echo "Scotiabank…"
dl "$DEST/scotiabank/scotiabank_seapal_marzo.pdf" "https://www.seapal.gob.mx/docs/transparencia_opd/Scotiabank-Marzo.pdf"
dl "$DEST/scotiabank/scotiabank_pv_2024_01.pdf" "https://transparencia.puertovallarta.gob.mx/transparenciaY/art8/V/estados-cuenta/2024/SCOTIABANK/01.Ene/SCOTIABANK%20ENERO%202024%20044375256032701744.pdf"
dl "$DEST/scotiabank/scotiabank_guadalajara_2021_08.pdf" "https://transparencia.guadalajara.gob.mx/sites/default/files/EstadoCuentaBancarioScotiabankAgosto21.pdf"

echo "BanBajío…"
dl "$DEST/banbajio/banbajio_tlaquepaque_2024_04.pdf" "https://apitransparencia.tlaquepaque.gob.mx/assets/biblioteca/c7133d955588468d416d8f0abe5b62fd.pdf"
dl "$DEST/banbajio/banbajio_guadalajara_2021_08.pdf" "https://transparencia.guadalajara.gob.mx/sites/default/files/EstadoCuentaBancarioBanBajioAgosto21.pdf"
dl "$DEST/banbajio/banbajio_guadalajara_2019_04.pdf" "https://transparencia.guadalajara.gob.mx/sites/default/files/EstadoCuentaBancarioBanBajioAbril19.pdf"

echo "Inbursa…"
dl "$DEST/inbursa/inbursa_cdmx_2018.pdf" "http://transparencia.finanzas.cdmx.gob.mx/repositorio/public/upload/repositorio/PLANEACION_FINANCIERA/ART_121/FRACC_XXIX/CRITERIO_22/INBURSA%20MSI%202018_Censurado.pdf"

echo "Azteca…"
dl "$DEST/azteca/azteca_seapal_2025_02.pdf" "https://www.seapal.gob.mx/docs/transparencia_opd/Azteca.pdf"
dl "$DEST/azteca/azteca_seapal_2024_02.pdf" "https://www.seapal.gob.mx/docs/transparencia_opd/Azteca-Feb-2024.pdf"
dl "$DEST/azteca/azteca_guadalajara_2022_04.pdf" "https://transparencia.guadalajara.gob.mx/sites/default/files/EstadoCuentaBancarioBancoAztecaAbril22.pdf"

echo "Banregio…"
dl "$DEST/banregio/banregio_guadalajara_2021_10.pdf" "https://transparencia.guadalajara.gob.mx/sites/default/files/EstadoCuentaBancarioBanregioOctubre21.pdf"
dl "$DEST/banregio/banregio_guadalajara_2021_04.pdf" "https://transparencia.guadalajara.gob.mx/sites/default/files/EstadoCuentaBancarioBanregioAbril21.pdf"
dl "$DEST/banregio/banregio_tlajomulco_2020_06.pdf" "https://www.tlajomulco.gob.mx/sites/default/files/transparencia/estados_de_cuenta/133031510015al30junio2020.pdf"

echo "Mifel…"
dl "$DEST/mifel/mifel_pv_2024_11.pdf" "https://transparencia.puertovallarta.gob.mx/transparenciaY/art8/V/estados-cuenta/2024/MIFEL/11.NOV/01600738840.pdf"

echo ""
echo "Listo. Total:"
find "$DEST" -name "*.pdf" | wc -l | xargs -I {} echo "  {} PDFs descargados"
du -sh "$DEST" | awk '{print "  "$1" en disco"}'
