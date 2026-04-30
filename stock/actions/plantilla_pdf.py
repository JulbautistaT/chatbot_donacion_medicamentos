from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from django.http import HttpResponse


def generar_acta_entrega(queryset):

    if not queryset.exists():
        return HttpResponse(
            "No hay solicitudes seleccionadas.",
            content_type='text/plain'
        )

    # Prefetch para evitar N+1 queries
    queryset = queryset.select_related('solicitante').prefetch_related(
        'detalles__medicamento',
        'formulas'
    )

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="acta_entrega.pdf"'

    doc = SimpleDocTemplate(
        response,
        pagesize=letter,
        rightMargin=30,
        leftMargin=30,
        topMargin=40,
        bottomMargin=40
    )

    styles = getSampleStyleSheet()

    # Estilos reutilizables
    style_celda = ParagraphStyle(
        'celda',
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
    )
    style_encabezado_col = ParagraphStyle(
        'encabezado_col',
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        alignment=TA_CENTER,
    )
    style_footer = ParagraphStyle(
        'footer',
        parent=styles["Normal"],
        fontSize=8,
        alignment=TA_RIGHT,
    )

    elements = []

    # Encabezado del documento
    elements.extend([
        Paragraph("<b>JUNTA ACUEDUCTO</b>", styles["Normal"]),
        Paragraph("NIT", styles["Normal"]),
        Paragraph("PERSONERIA JURIDICA", styles["Normal"]),
        Spacer(1, 10),
        Paragraph("<b>ENTREGA DE MEDICAMENTOS</b>", styles["Title"]),
        Spacer(1, 15),
    ])

    # Cabecera de la tabla
    data = [[
        Paragraph("<b>Fecha</b>", style_encabezado_col),
        Paragraph("<b>Nombre completo</b>", style_encabezado_col),
        Paragraph("<b>Medicamento</b>", style_encabezado_col),
        Paragraph("<b>Teléfono</b>", style_encabezado_col),
        Paragraph("<b>Firma</b>", style_encabezado_col),
        Paragraph("<b>¿Requiere fórmula?</b>", style_encabezado_col),
    ]]

    for solicitud in queryset:
        tiene_formula = bool(solicitud.formulas.all())  # aprovecha el prefetch
        for detalle in solicitud.detalles.all():
            data.append([
                Paragraph(solicitud.fecha.strftime('%d-%m-%Y'), style_celda),
                Paragraph(solicitud.solicitante.nombre or "", style_celda),
                Paragraph(
                    f"{detalle.medicamento.nombre_comercial} "
                    f"{detalle.medicamento.concentracion}",
                    style_celda
                ),
                Paragraph(solicitud.solicitante.telefono or "", style_celda),
                "",  # espacio para firma
                Paragraph("Sí" if tiene_formula else "No", style_celda),
            ])

    table = Table(data, colWidths=[60, 120, 140, 80, 80, 80])
    table.setStyle(TableStyle([
        ('GRID',       (0, 0), (-1, -1), 1,   colors.black),
        ('BACKGROUND', (0, 0), (-1,  0), colors.lightgrey),
        ('ALIGN',      (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 20))
    elements.append(
        Paragraph("EL AGUA ES VIDA, APRECIÉMOSLA, NO LA DERROCHEMOS", style_footer)
    )

    doc.build(elements)
    return response