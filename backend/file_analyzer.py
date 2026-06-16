import os
import json
import mimetypes
from pathlib import Path
import PyPDF2
from PIL import Image
import pandas as pd
import numpy as np
from datetime import datetime

class FileAnalyzer:
    def __init__(self, upload_folder='data/files'):
        self.upload_folder = upload_folder
        os.makedirs(upload_folder, exist_ok=True)
    
    def analyze_file(self, file_path, filename):
        """Analyze file and extract information based on file type"""
        file_info = {
            'filename': filename,
            'path': file_path,
            'size': os.path.getsize(file_path),
            'type': self._get_file_type(file_path),
            'created': datetime.fromtimestamp(os.path.getctime(file_path)).isoformat(),
            'modified': datetime.fromtimestamp(os.path.getmtime(file_path)).isoformat(),
            'analysis': {}
        }
        
        # Analyze based on file type
        try:
            if file_info['type'] == 'pdf':
                file_info['analysis'] = self._analyze_pdf(file_path)
            elif file_info['type'] == 'image':
                file_info['analysis'] = self._analyze_image(file_path)
            elif file_info['type'] == 'text':
                file_info['analysis'] = self._analyze_text(file_path)
            elif file_info['type'] == 'code':
                file_info['analysis'] = self._analyze_code(file_path)
            elif file_info['type'] == 'data':
                file_info['analysis'] = self._analyze_data(file_path)
            else:
                file_info['analysis'] = self._analyze_generic(file_path)
        except Exception as e:
            file_info['analysis'] = {
                'error': str(e),
                'status': 'analysis_failed'
            }
        
        return file_info
    
    def _get_file_type(self, file_path):
        """Determine file type from extension and content"""
        mime_type, _ = mimetypes.guess_type(file_path)
        ext = Path(file_path).suffix.lower()
        
        if mime_type:
            if 'pdf' in mime_type:
                return 'pdf'
            elif 'image' in mime_type:
                return 'image'
            elif 'text' in mime_type:
                return 'text'
            elif 'json' in mime_type or ext in ['.json']:
                return 'data'
            elif 'csv' in mime_type or ext in ['.csv']:
                return 'data'
            elif 'excel' in mime_type or ext in ['.xls', '.xlsx']:
                return 'data'
        
        # Check for code files by extension
        code_extensions = ['.py', '.js', '.java', '.cpp', '.c', '.html', '.css', '.php', '.rb', '.go', '.rs']
        if ext in code_extensions:
            return 'code'
        
        return 'generic'
    
    def _analyze_pdf(self, file_path):
        """Extract information from PDF files"""
        analysis = {'type': 'pdf', 'pages': 0, 'text': '', 'metadata': {}}
        
        try:
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                analysis['pages'] = len(pdf_reader.pages)
                
                # Extract text from first few pages
                text_content = []
                for i in range(min(10, analysis['pages'])):  # Limit to first 10 pages
                    page = pdf_reader.pages[i]
                    text = page.extract_text()
                    if text:
                        text_content.append(text[:1000])  # Limit text length
                
                analysis['text'] = '\n\n'.join(text_content)
                analysis['metadata'] = pdf_reader.metadata or {}
                
                # Basic statistics
                analysis['has_text'] = len(analysis['text']) > 0
                analysis['estimated_words'] = len(analysis['text'].split())
                
        except Exception as e:
            analysis['error'] = f"PDF analysis error: {str(e)}"
        
        return analysis
    
    def _analyze_image(self, file_path):
        """Extract information from image files"""
        analysis = {'type': 'image', 'dimensions': None, 'format': None}
        
        try:
            with Image.open(file_path) as img:
                analysis['dimensions'] = img.size
                analysis['format'] = img.format
                analysis['mode'] = img.mode
                analysis['info'] = img.info
                
                # Calculate file size in readable format
                file_size = os.path.getsize(file_path)
                analysis['size_kb'] = file_size / 1024
                
                # Check if image is large
                analysis['is_large'] = file_size > 5 * 1024 * 1024  # >5MB
                
        except Exception as e:
            analysis['error'] = f"Image analysis error: {str(e)}"
        
        return analysis
    
    def _analyze_text(self, file_path):
        """Analyze text files"""
        analysis = {'type': 'text', 'lines': 0, 'words': 0, 'chars': 0, 'content_preview': ''}
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
                content = file.read()
                
                analysis['lines'] = len(content.split('\n'))
                analysis['words'] = len(content.split())
                analysis['chars'] = len(content)
                analysis['content_preview'] = content[:500]  # First 500 chars
                
                # Detect language patterns
                analysis['has_code'] = any(keyword in content.lower() for keyword in 
                                         ['def ', 'function ', 'class ', 'import ', 'export ', '<html>'])
                
        except Exception as e:
            analysis['error'] = f"Text analysis error: {str(e)}"
        
        return analysis
    
    def _analyze_code(self, file_path):
        """Analyze code files"""
        analysis = {'type': 'code', 'language': '', 'lines': 0, 'functions': 0, 'classes': 0}
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
                content = file.read()
                lines = content.split('\n')
                
                analysis['lines'] = len(lines)
                analysis['language'] = self._detect_language(file_path)
                
                # Basic code analysis
                analysis['functions'] = len([l for l in lines if 'def ' in l or 'function ' in l])
                analysis['classes'] = len([l for l in lines if 'class ' in l])
                analysis['imports'] = len([l for l in lines if 'import ' in l or 'from ' in l])
                
                # Complexity metrics
                analysis['avg_line_length'] = sum(len(l) for l in lines) / max(1, len(lines))
                analysis['comments'] = len([l for l in lines if l.strip().startswith('#') or '//' in l])
                
        except Exception as e:
            analysis['error'] = f"Code analysis error: {str(e)}"
        
        return analysis
    
    def _analyze_data(self, file_path):
        """Analyze data files (CSV, JSON, Excel)"""
        analysis = {'type': 'data', 'rows': 0, 'columns': 0, 'format': ''}
        ext = Path(file_path).suffix.lower()
        
        try:
            if ext == '.csv':
                df = pd.read_csv(file_path)
                analysis['format'] = 'csv'
            elif ext == '.json':
                df = pd.read_json(file_path)
                analysis['format'] = 'json'
            elif ext in ['.xls', '.xlsx']:
                df = pd.read_excel(file_path)
                analysis['format'] = 'excel'
            else:
                return {'type': 'data', 'error': 'Unsupported data format'}
            
            analysis['rows'] = len(df)
            analysis['columns'] = len(df.columns)
            analysis['column_names'] = df.columns.tolist()
            analysis['dtypes'] = df.dtypes.astype(str).to_dict()
            
            # Basic statistics for numeric columns
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            if len(numeric_cols) > 0:
                analysis['numeric_stats'] = df[numeric_cols].describe().to_dict()
            
            # Check for missing values
            missing = df.isnull().sum()
            analysis['missing_values'] = missing[missing > 0].to_dict()
            
        except Exception as e:
            analysis['error'] = f"Data analysis error: {str(e)}"
        
        return analysis
    
    def _analyze_generic(self, file_path):
        """Generic file analysis"""
        return {
            'type': 'generic',
            'size': os.path.getsize(file_path),
            'readable': os.access(file_path, os.R_OK),
            'analysis_time': datetime.now().isoformat()
        }
    
    def _detect_language(self, file_path):
        """Detect programming language from file extension"""
        ext_map = {
            '.py': 'Python',
            '.js': 'JavaScript',
            '.java': 'Java',
            '.cpp': 'C++',
            '.c': 'C',
            '.html': 'HTML',
            '.css': 'CSS',
            '.php': 'PHP',
            '.rb': 'Ruby',
            '.go': 'Go',
            '.rs': 'Rust',
            '.ts': 'TypeScript',
            '.swift': 'Swift',
            '.kt': 'Kotlin',
            '.sql': 'SQL',
            '.sh': 'Shell',
            '.md': 'Markdown',
            '.json': 'JSON',
            '.xml': 'XML',
            '.yml': 'YAML',
            '.yaml': 'YAML'
        }
        
        ext = Path(file_path).suffix.lower()
        return ext_map.get(ext, 'Unknown')