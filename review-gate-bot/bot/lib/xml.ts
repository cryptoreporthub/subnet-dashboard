/**
 * Is this one whole XML document?
 *
 * Not a validator and not a parser. It answers the single question the suite
 * gate needs answered before it believes a report: did the file arrive
 * complete? A report cut off mid-run still contains complete `<testcase>`
 * elements, so a reader that only matches those elements counts them and
 * compares clean.
 *
 * The check is structural: every start tag closes in order, there is exactly
 * one root, and nothing but comments and whitespace follows it. Text, entities
 * and attribute values are not interpreted.
 */

const TOKEN =
  /<!--[\s\S]*?-->|<\?[\s\S]*?\?>|<!\[CDATA\[[\s\S]*?\]\]>|<!DOCTYPE[^>]*>|<\/([A-Za-z_][\w:.-]*)\s*>|<([A-Za-z_][\w:.-]*)((?:\s+[\w:.-]+\s*=\s*(?:"[^"]*"|'[^']*'))*)\s*(\/?)>/gy;

export class MalformedXmlError extends Error {
  constructor(detail: string) {
    super(`malformed XML: ${detail}`);
    this.name = "MalformedXmlError";
  }
}

/** Throws `MalformedXmlError` unless `xml` is one complete document. */
export function assertWellFormed(xml: string): void {
  const open: string[] = [];
  let roots = 0;
  let position = 0;

  while (position < xml.length) {
    const next = xml.indexOf("<", position);
    const text = xml.slice(position, next === -1 ? xml.length : next);
    if (text.trim() !== "" && (open.length === 0 || next === -1)) {
      throw new MalformedXmlError(open.length === 0 ? "text outside the root element" : "text after the last tag");
    }
    if (next === -1) {
      break;
    }

    TOKEN.lastIndex = next;
    const token = TOKEN.exec(xml);
    if (token === null) {
      throw new MalformedXmlError(`unreadable markup at offset ${next}`);
    }
    position = TOKEN.lastIndex;

    const [, closing, opening, , selfClosing] = token;
    if (closing !== undefined) {
      const expected = open.pop();
      if (expected !== closing) {
        throw new MalformedXmlError(`</${closing}> closes ${expected === undefined ? "nothing" : `<${expected}>`}`);
      }
    } else if (opening !== undefined) {
      if (open.length === 0) {
        roots += 1;
        if (roots > 1) {
          throw new MalformedXmlError("more than one root element");
        }
      }
      if (selfClosing !== "/") {
        open.push(opening);
      }
    }
  }

  if (open.length > 0) {
    throw new MalformedXmlError(`<${open[open.length - 1]}> is never closed (report cut off?)`);
  }
  if (roots === 0) {
    throw new MalformedXmlError("no root element");
  }
}
