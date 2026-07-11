import re
from typing import Optional, Tuple, List
from enum import Enum


class ResponseType(Enum):
    DART_CODE = "dart_code"
    EXPLANATION = "explanation"
    ERROR = "error"
    EMPTY = "empty"


class IAResponseValidator:
    def __init__(self):
        self.code_patterns = [
            (r'```dart\n(.*?)```', re.DOTALL),
            (r'```flutter\n(.*?)```', re.DOTALL),
            (r'```\n(.*?)```', re.DOTALL),
            (r'`(import\s+.*?`(?:.*?`)?)', re.DOTALL),
            (r'^(import\s+.*?)(?=\n\s*\n|$)', re.DOTALL | re.MULTILINE),
            (r'^(class\s+.*?)(?=\n\s*\n|$)', re.DOTALL | re.MULTILINE),
        ]
        self.non_code_indicators = [
            r'^(aqui est[aá]|aqui|o c[oó]digo|explica[cç][aã]o|vou|precisamos|recomendo|aqui est[áa] o c[óo]digo corrigido)',
            r'^[A-Z][a-z]+:',
            r'^[0-9]+\.',
        ]

    def validate_and_extract(self, response: str, file_path: str = 'main.dart') -> Tuple[bool, Optional[str], List[str]]:
        errors = []
        if not response or not response.strip():
            return False, None, ["Resposta vazia"]
        cleaned = self._clean_response(response)
        response_type = self._detect_response_type(cleaned)
        if response_type == ResponseType.ERROR:
            return False, None, ["Resposta parece ser um erro"]
        if response_type == ResponseType.EXPLANATION:
            extracted = self._extract_code_from_text(cleaned)
            if not extracted:
                return False, None, ["Resposta não contém código Dart válido"]
            cleaned = extracted
        elif response_type == ResponseType.EMPTY:
            return False, None, ["Resposta vazia ou apenas texto irrelevante"]
        extracted_code = self._extract_dart_code(cleaned)
        if not extracted_code:
            extracted_code = self._find_dart_constructs(cleaned)
        if not extracted_code:
            return False, None, ["Não foi possível extrair código Dart válido"]
        is_valid, syntax_errors = self._validate_dart_syntax(extracted_code)
        if not is_valid:
            corrected = self._attempt_syntax_fix(extracted_code, syntax_errors)
            if corrected:
                return True, corrected, ["Sintaxe corrigida automaticamente"]
            return False, None, [f"Erros de sintaxe: {syntax_errors[:3]}"]
        if 'main.dart' in file_path:
            if 'void main()' not in extracted_code and 'runApp' not in extracted_code:
                errors.append("Código não parece ser um main.dart válido (falta void main ou runApp)")
        return True, extracted_code, errors

    def force_code_extraction(self, response: str) -> Optional[str]:
        if not response or len(response.strip()) < 50:
            return None
        code_match = re.search(r'```(?:dart)?\s*\n(.*?)\n```', response, re.DOTALL)
        if code_match:
            extracted = code_match.group(1).strip()
            if self._looks_like_dart(extracted):
                return extracted
        if 'import' in response and ('class' in response or 'void main' in response):
            lines = [l.rstrip() for l in response.split('\n') if l.strip()]
            dart_block = []
            in_block = False
            for line in lines:
                if line.startswith('import ') or line.startswith('class ') or line.startswith('void '):
                    in_block = True
                if in_block:
                    dart_block.append(line)
            if dart_block and self._looks_like_dart('\n'.join(dart_block)):
                return '\n'.join(dart_block)
        return None

    def _clean_response(self, response: str) -> str:
        cleaned = re.sub(r'^#+\s+.*?\n', '', response, flags=re.MULTILINE)
        cleaned = re.sub(r'^[-=*]{3,}\s*$', '', cleaned, flags=re.MULTILINE)
        cleaned = '\n'.join(line for line in cleaned.split('\n') if line.strip())
        return cleaned

    def _detect_response_type(self, response: str) -> ResponseType:
        if not response:
            return ResponseType.EMPTY
        lower = response.lower()
        if any(re.search(pattern, lower) for pattern in self.non_code_indicators):
            return ResponseType.EXPLANATION
        if any(re.search(pattern, response, flags) for pattern, flags in self.code_patterns):
            return ResponseType.DART_CODE
        if lower.startswith(('error', 'erro', 'exception', 'falha', 'timeout')):
            return ResponseType.ERROR
        return ResponseType.DART_CODE

    def _extract_code_from_text(self, text: str) -> Optional[str]:
        patterns = [
            r'```(?:dart|flutter)?\s*\n(.*?)\n```',
            r'`([^`]+)`',
            r'(\b(?:import|class|void|Widget|const|final|var)\s+[^\n]+)',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, text, re.DOTALL)
            if matches:
                code_parts = []
                for match in matches:
                    if self._looks_like_dart(match):
                        code_parts.append(match.strip())
                if code_parts:
                    return '\n\n'.join(code_parts)
        return None

    def _extract_dart_code(self, text: str) -> Optional[str]:
        for pattern, flags in self.code_patterns:
            matches = re.findall(pattern, text, flags)
            if matches:
                for match in matches:
                    if self._looks_like_dart(match):
                        return match.strip()
        return None

    def _find_dart_constructs(self, text: str) -> Optional[str]:
        lines = text.split('\n')
        dart_lines = []
        in_dart_block = False
        for line in lines:
            if self._looks_like_dart(line):
                dart_lines.append(line)
                in_dart_block = True
            elif in_dart_block and line.strip() and not line.strip().startswith('//'):
                if self._could_be_dart_continuation(line):
                    dart_lines.append(line)
                else:
                    in_dart_block = False
        if dart_lines:
            return '\n'.join(dart_lines)
        return None

    def _looks_like_dart(self, text: str) -> bool:
        dart_keywords = [
            'import', 'class', 'void', 'Widget', 'const', 'final', 'var',
            'String', 'int', 'double', 'bool', 'List', 'Map', 'Future',
            'async', 'await', 'return', 'if', 'else', 'for', 'while',
            'runApp', 'MaterialApp', 'Scaffold', 'StatefulWidget',
            'StatelessWidget', 'build', 'context'
        ]
        text_lower = text.lower()
        keyword_count = sum(1 for kw in dart_keywords if kw in text_lower)
        return keyword_count >= 2 and len(text.strip()) > 20

    def _could_be_dart_continuation(self, line: str) -> bool:
        line = line.strip()
        if not line:
            return False
        return (line.startswith(('//', '/*', '*/')) or
                line.endswith((';', '{', '}', ')')) or
                '()' in line or '=>' in line)

    def _validate_dart_syntax(self, code: str) -> Tuple[bool, List[str]]:
        errors = []
        if not self._balanced('{', '}', code):
            errors.append("Chaves desbalanceadas")
        if not self._balanced('(', ')', code):
            errors.append("Parênteses desbalanceados")
        import_lines = [l for l in code.split('\n') if l.strip().startswith('import')]
        for imp in import_lines:
            if not imp.strip().endswith(';'):
                errors.append(f"Import sem ponto e vírgula: {imp[:30]}...")
        if not re.search(r'\b(class|void)\s+\w+', code):
            errors.append("Nenhuma classe ou função encontrada")
        return len(errors) == 0, errors

    def _balanced(self, open_char: str, close_char: str, text: str) -> bool:
        count = 0
        for char in text:
            if char == open_char:
                count += 1
            elif char == close_char:
                count -= 1
                if count < 0:
                    return False
        return count == 0

    def _attempt_syntax_fix(self, code: str, errors: List[str]) -> Optional[str]:
        fixed = code
        if any('ponto e vírgula' in e for e in errors):
            lines = fixed.split('\n')
            for i, line in enumerate(lines):
                if line.strip() and not line.strip().endswith(';') and not line.strip().endswith('{'):
                    if not line.strip().startswith(('import', 'class', 'void', 'Widget')):
                        if '()' in line or '=>' in line:
                            lines[i] = line + ';'
            fixed = '\n'.join(lines)
        if any('Import sem ponto e vírgula' in e for e in errors):
            fixed = re.sub(r'(import\s+[^\n;]+)(\s*\n)', r'\1;\2', fixed)
        return fixed
