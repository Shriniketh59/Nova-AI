import { PdfIngestor } from './ingestors/pdfIngestor.js';
import { TextIngestor } from './ingestors/textIngestor.js';
import { CsvIngestor } from './ingestors/csvIngestor.js';
import { ExcelIngestor } from './ingestors/excelIngestor.js';
import { DocxIngestor } from './ingestors/docxIngestor.js';
import { PptxIngestor } from './ingestors/pptxIngestor.js';
import { CodeIngestor } from './ingestors/codeIngestor.js';
import { RepoIngestor } from './ingestors/repoIngestor.js';
import { WebIngestor } from './ingestors/webIngestor.js';
import { YoutubeIngestor } from './ingestors/youtubeIngestor.js';
import { AudioIngestor } from './ingestors/audioIngestor.js';
import { VideoIngestor } from './ingestors/videoIngestor.js';

const MIME_MAP = {
  'application/pdf': () => new PdfIngestor(),
  'text/plain': () => new TextIngestor(),
  'text/markdown': () => new TextIngestor(),
  'text/csv': () => new CsvIngestor(),
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': () => new DocxIngestor(),
  'application/vnd.openxmlformats-officedocument.presentationml.presentation': () => new PptxIngestor(),
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': () => new ExcelIngestor(),
  'application/vnd.ms-excel': () => new ExcelIngestor()
};

const CODE_EXTENSIONS = new Set(['.js', '.ts', '.jsx', '.tsx', '.py', '.java', '.cpp', '.c', '.h', '.hpp']);

const SOURCE_TYPE_MAP = {
  web: () => new WebIngestor(),
  youtube: () => new YoutubeIngestor(),
  audio: () => new AudioIngestor(),
  video: () => new VideoIngestor(),
  repo: () => new RepoIngestor()
};

/**
 * Resolves the right ingestor for an uploaded file or external source.
 * @param {{ mimeType?: string, extension?: string, sourceType?: string }} descriptor
 */
export function resolveIngestor({ mimeType, extension, sourceType } = {}) {
  if (sourceType && SOURCE_TYPE_MAP[sourceType]) {
    return SOURCE_TYPE_MAP[sourceType]();
  }
  if (extension && CODE_EXTENSIONS.has(extension.toLowerCase())) {
    return new CodeIngestor();
  }
  if (mimeType && MIME_MAP[mimeType]) {
    return MIME_MAP[mimeType]();
  }
  throw new Error(`No ingestor registered for mimeType=${mimeType} extension=${extension} sourceType=${sourceType}`);
}
