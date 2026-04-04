import io
import fitz  # PyMuPDF
from docx import Document

class DocumentParser:
    """Handles extracting raw text securely from multiple file formats."""

    @staticmethod
    def parse_pdf(file_bytes: bytes) -> str:
        """Extracts text from a highly standard or complex PDF using PyMuPDF."""
        text = []
        # Open PDF from memory stream
        try:
            with fitz.open(stream=file_bytes, filetype="pdf") as doc:
                for page in doc:
                    text.append(page.get_text("text"))
        except Exception as e:
            raise ValueError(f"Failed to parse PDF document: {str(e)}")
        
        return "\n\n".join(text)

    @staticmethod
    def parse_docx(file_bytes: bytes) -> str:
        """Extracts text from a Microsoft Word Document."""
        text = []
        try:
            doc = Document(io.BytesIO(file_bytes))
            for paragraph in doc.paragraphs:
                if paragraph.text.strip():
                    text.append(paragraph.text.strip())
        except Exception as e:
            raise ValueError(f"Failed to parse DOCX document: {str(e)}")
            
        return "\n".join(text)

    @staticmethod
    def parse_txt(file_bytes: bytes) -> str:
        """Extracts UTF-8 or compatible text from a flat text file."""
        try:
            return file_bytes.decode('utf-8')
        except UnicodeDecodeError:
            try:
                # Fallback to loose encoding if Windows latin-1 is heavily used
                return file_bytes.decode('latin-1')
            except Exception as e:
                raise ValueError(f"Failed to parse text file strictly: {str(e)}")

    @classmethod
    def extract_text(cls, filename: str, file_bytes: bytes) -> str:
        """Main routing method to extract text based on strict filename extension routing."""
        ext = filename.lower().split('.')[-1]
        
        if ext == 'pdf':
            return cls.parse_pdf(file_bytes)
        elif ext in ['docx', 'doc']:
            # Note: docx is supported, legacy doc uses complex binary formats not natively parsed by python-docx
            # but we route it hoping the magic bites or we allow failure parsing.
            return cls.parse_docx(file_bytes)
        elif ext == 'txt':
            return cls.parse_txt(file_bytes)
        else:
            raise ValueError(f"Unsupported document format: .{ext}. Please upload PDF, DOCX, or TXT.")

document_parser = DocumentParser()
