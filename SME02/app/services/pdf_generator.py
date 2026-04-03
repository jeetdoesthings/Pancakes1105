"""
PDF Generator Service (ReportLab Edition)
=========================================
Generates professional, boardroom-ready PDF quotations 
using ReportLab Platypus. High-fidelity, zero-dependency engine.
"""

import os
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, 
    PageBreak, Image
)
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT

from app.models import ExtractedRequirements, PricingStrategy, ProposalDraft
from app.config import settings


class PDFGenerator:
    """Generates professional PDF quotations from proposal data using ReportLab."""

    def __init__(self):
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

    def _setup_custom_styles(self):
        """Create a professional design system for the PDF."""
        # Main Title Style
        self.styles.add(ParagraphStyle(
            name='QuotationTitle',
            parent=self.styles['Heading1'],
            fontSize=28,
            leading=34,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#1A365D"),  # Deep Navy
            spaceAfter=20
        ))
        
        # Section Header Style
        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=self.styles['Heading2'],
            fontSize=16,
            leading=20,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#2B6CB0"),  # Medium Blue
            spaceBefore=15,
            spaceAfter=10,
            borderPadding=(0, 0, 5, 0),
            borderWidth=0,
            borderColor=colors.HexColor("#E2E8F0")
        ))

        # Body Text Style
        self.styles.add(ParagraphStyle(
            name='BodyTextMod',
            parent=self.styles['Normal'],
            fontSize=11,
            leading=14,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#4A5568"),  # Slate Gray
            spaceAfter=8
        ))

        # Table Header Style
        self.styles.add(ParagraphStyle(
            name='TableHeader',
            parent=self.styles['Normal'],
            fontSize=10,
            leading=12,
            alignment=TA_LEFT,
            textColor=colors.whitesmoke,
            fontName='Helvetica-Bold'
        ))

    def _format_currency(self, value, currency="INR"):
        if currency == "INR":
            return f"Rs. {value:,.0f}"
        elif currency == "USD":
            return f"${value:,.2f}"
        return f"{currency} {value:,.2f}"

    def generate(
        self,
        job_id: str,
        requirements: ExtractedRequirements,
        pricing: PricingStrategy,
        proposal: ProposalDraft,
        company_name: str = "Ering Solutions",
        contact_name: str = "Sales Team",
        contact_email: str = "sales@eringsolutions.com",
        contact_phone: str = "+91-9876543210",
    ) -> str:
        """Generate a PDF quotation using ReportLab and return the file path."""
        output_filename = f"quotation_{job_id}.pdf"
        output_path = os.path.join(settings.OUTPUT_DIR, output_filename)
        
        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            rightMargin=50,
            leftMargin=50,
            topMargin=50,
            bottomMargin=50
        )
        
        story = []
        
        # --- COVER PAGE ---
        story.append(Spacer(1, 2*inch))
        story.append(Paragraph("BUSINESS QUOTATION", self.styles['QuotationTitle']))
        story.append(Paragraph(f"Project: {requirements.project_name or 'Strategic Proposal'}", self.styles['Heading2']))
        story.append(Spacer(1, 0.5*inch))
        
        story.append(Paragraph(f"<b>Prepared for:</b> {requirements.issuing_company or 'Valued Client'}", self.styles['BodyTextMod']))
        story.append(Paragraph(f"<b>Date:</b> {datetime.now().strftime('%B %d, %Y')}", self.styles['BodyTextMod']))
        story.append(Paragraph(f"<b>Proposal ID:</b> SME02-{job_id.upper()}", self.styles['BodyTextMod']))
        
        story.append(Spacer(1, 2*inch))
        story.append(Paragraph(f"<b>From:</b> {company_name}", self.styles['BodyTextMod']))
        story.append(Paragraph(f"Contact: {contact_name}", self.styles['BodyTextMod']))
        story.append(Paragraph(contact_email, self.styles['BodyTextMod']))
        story.append(Paragraph(contact_phone, self.styles['BodyTextMod']))
        
        story.append(PageBreak())
        
        # --- EXECUTIVE SUMMARY ---
        story.append(Paragraph("Executive Summary", self.styles['SectionHeader']))
        story.append(Paragraph(proposal.executive_summary or "Proposal details follow.", self.styles['BodyTextMod']))
        
        # --- PRICING TABLE ---
        story.append(Paragraph("Commercial Proposal", self.styles['SectionHeader']))
        
        data = [[
            Paragraph("<b>Item Description</b>", self.styles['TableHeader']), 
            Paragraph("<b>Qty</b>", self.styles['TableHeader']), 
            Paragraph("<b>Unit Price</b>", self.styles['TableHeader']), 
            Paragraph("<b>Total</b>", self.styles['TableHeader'])
        ]]
        
        for item in pricing.line_items:
            data.append([
                Paragraph(f"<b>{item.item_name}</b><br/><font size='9'>{item.description}</font>", self.styles['BodyTextMod']),
                str(item.quantity),
                self._format_currency(item.unit_price, pricing.currency),
                self._format_currency(item.total_price, pricing.currency)
            ])
            
        # Summary rows
        data.append(["", "", "Subtotal", self._format_currency(pricing.subtotal, pricing.currency)])
        data.append(["", "", f"Tax ({int(pricing.tax_rate*100)}%)", self._format_currency(pricing.tax_amount, pricing.currency)])
        data.append(["", "", Paragraph("<b>GRAND TOTAL</b>", self.styles['BodyTextMod']), 
                    Paragraph(f"<b>{self._format_currency(pricing.total, pricing.currency)}</b>", self.styles['BodyTextMod'])])
        
        table = Table(data, colWidths=[3.2*inch, 0.6*inch, 1.2*inch, 1.2*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1A365D")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -4), colors.HexColor("#F7FAFC")),
            ('GRID', (0, 0), (-1, -4), 0.5, colors.HexColor("#E2E8F0")),
            ('LINEBELOW', (0, -3), (-1, -1), 1, colors.HexColor("#2B6CB0")),
            ('ALIGN', (2, -3), (3, -1), 'RIGHT'),
        ]))
        story.append(table)
        
        # --- PROPOSAL DETAILS ---
        if proposal.technical_proposal:
            story.append(Paragraph("Technical Specifications", self.styles['SectionHeader']))
            for section in proposal.technical_proposal:
                story.append(Paragraph(section.title, self.styles['Heading3']))
                story.append(Paragraph(section.content, self.styles['BodyTextMod']))
                story.append(Spacer(1, 0.1*inch))
                
        # --- TERMS AND CONDITIONS ---
        story.append(Paragraph("Terms and Conditions", self.styles['SectionHeader']))
        story.append(Paragraph(proposal.terms_and_conditions or "Standard terms apply.", self.styles['BodyTextMod']))
        
        # Build document
        doc.build(story)
        return output_path
