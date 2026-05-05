import os
from django.http import HttpResponse

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    Image,
    HRFlowable
)

# Colores
COLOR_HEADER_BG = colors.HexColor('#1a5276')
COLOR_HEADER_TEXT = colors.white
COLOR_ROW_ALT = colors.HexColor('#eaf4fb')
COLOR_GRID = colors.HexColor('#aed6f1')

PAGE_WIDTH = 732


def generar_acta_entrega(queryset):

    if not queryset.exists():
        return HttpResponse(
            "No hay solicitudes seleccionadas.",
            content_type="text/plain"
        )

    queryset = queryset.select_related(
        'solicitante'
    ).prefetch_related(
        'detalles__medicamento',
        'formulas'
    )

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = (
        'attachment; filename="acta_entrega.pdf"'
    )

    doc = SimpleDocTemplate(
        response,
        pagesize=landscape(letter),
        leftMargin=30,
        rightMargin=30,
        topMargin=30,
        bottomMargin=30
    )

    styles = getSampleStyleSheet()


    style_info = ParagraphStyle(
        'info',
        parent=styles["Normal"],
        fontSize=9,
        leading=12
    )

    style_title = ParagraphStyle(
        'title',
        parent=styles["Normal"],
        fontSize=18,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
        textColor=COLOR_HEADER_BG
    )

    style_header_col = ParagraphStyle(
        'header_col',
        parent=styles["Normal"],
        fontSize=8,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
        textColor=COLOR_HEADER_TEXT
    )

    style_cell = ParagraphStyle(
        'cell',
        parent=styles["Normal"],
        fontSize=8
    )

    style_footer = ParagraphStyle(
        'footer',
        parent=styles["Normal"],
        fontSize=8,
        alignment=TA_RIGHT
    )

    elements = []


    logo_path = os.path.join(
        os.getcwd(),
        "utils",
        "Logotipo.png"
    )

    logo = (
        Image(logo_path, width=70, height=70)
        if os.path.exists(logo_path)
        else Paragraph("", styles["Normal"])
    )

    info_text = [
        Paragraph("<b>JUNTA ACUEDUCTO COMUNITARIO POPULAR 1</b>", style_info),
        Paragraph("NIT: 96120965-6", style_info),
        Paragraph("PERSONERÍA JURÍDICA 3554", style_info),
    ]

    header_table = Table(
        [[
            logo,
            info_text,
            Paragraph(
                "<b>ENTREGA DE MEDICAMENTOS</b>",
                style_title
            )
        ]],
        colWidths=[80, 220, 430]
    )

    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')
    ]))

    elements.append(header_table)
    elements.append(
        HRFlowable(
            width="100%",
            thickness=1,
            color=COLOR_HEADER_BG
        )
    )
    elements.append(Spacer(1, 15))


    data = [[
        Paragraph("Fecha", style_header_col),
        Paragraph("Nombre completo", style_header_col),
        Paragraph("Medicamento", style_header_col),
        Paragraph("Teléfono", style_header_col),
        Paragraph("Firma", style_header_col),
        Paragraph("¿Requiere fórmula?", style_header_col),
    ]]

    for solicitud in queryset:
        tiene_formula = solicitud.formulas.exists()

        for detalle in solicitud.detalles.all():
            data.append([
                Paragraph(
                    solicitud.fecha.strftime('%d-%m-%Y'),
                    style_cell
                ),
                Paragraph(
                    solicitud.solicitante.nombre or "",
                    style_cell
                ),
                Paragraph(
                    f"{detalle.medicamento.nombre_comercial} "
                    f"{detalle.medicamento.concentracion}",
                    style_cell
                ),
                Paragraph(
                    solicitud.solicitante.telefono or "",
                    style_cell
                ),
                "",
                Paragraph(
                    "Sí" if tiene_formula else "No",
                    style_cell
                )
            ])

    table = Table(
        data,
        colWidths=[80, 170, 220, 100, 100, 100],
        repeatRows=1
    )

    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), COLOR_HEADER_BG),
        ('TEXTCOLOR', (0, 0), (-1, 0), COLOR_HEADER_TEXT),
        ('GRID', (0, 0), (-1, -1), 0.5, COLOR_GRID),
        ('ROWBACKGROUNDS',
         (0, 1),
         (-1, -1),
         [colors.white, COLOR_ROW_ALT]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')
    ]))

    elements.append(table)


    elements.append(Spacer(1, 20))
    elements.append(
        Paragraph(
            "EL AGUA ES VIDA, APRECIÉMOSLA, NO LA DERROCHEMOS",
            style_footer
        )
    )

    doc.build(elements)
    return response