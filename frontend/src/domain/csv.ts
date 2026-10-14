/** Spreadsheet-safe CSV, including user-controlled names and conclusions. */
export function csvDocument(rows: unknown[][]): string {
  const cell = (value: unknown) => {
    let text = String(value ?? '')
    if (/^[\s\uFEFF]*[=+@-]/.test(text) || /^[\t\r\n]/.test(text)) text = "'" + text
    return '"' + text.replace(/"/g, '""') + '"'
  }
  return '\uFEFF' + rows.map(row => row.map(cell).join(',')).join('\r\n')
}
