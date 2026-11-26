# MarketStudio Design System
Direction approved: Modern Minimalist × Enterprise Commerce (A+B), satu accent #2563EB, navy, putih dan coffee dark, customizable. Token berikut selain accent adalah proposal. Logo raster terakhir di assets/branding/logo-reference.png; jangan mengklaim SVG master.

## Brand dan tokens
| Token | Light candidate | Dark candidate |
|---|---|---|
| accent | #2563EB | #2563EB (uji contrast) |
| brand navy | #142B52 | #142B52 |
| canvas | #F7F8FA | #141210 |
| surface | #FFFFFF | #1C1917 |
| surface elevated | #EFF6FF | #292524 |
| text | #172033 | #F5F5F4 |
| border | #E2E6EC | perlu contrast test |

Primitive → semantic → component tokens. Semantic success/warning/error tidak berubah mengikuti accent. Theme system/light/coffee dark; custom accent divalidasi contrast dan fallback. Preferensi lokal untuk fast startup, sync server opsional. Geist Sans/Mono kandidat; base 14, section 18, heading 24, display 32, tabular nums. Spacing 4px grid; radius 8px; desktop button 36px, touch target 44px kandidat. Jangan menyatakan WCAG compliant tanpa audit.

## Layout dan interaction
Desktop rail 64, sidebar 240, header 56, AI panel 360, content padding 24 kandidat. Mobile gunakan responsive navigation dan panel yang tidak menutup task utama. Studio dibedakan icon/nama, bukan warna berbeda. Empty state memberi next action; loading skeleton tidak menyatakan data aktual; error menampilkan recovery; destructive action confirmation; save state jelas. Financial card membedakan actual/estimate/simulation, period, unit dan drill-down. Chart tidak hanya mengandalkan warna; table punya header dan keyboard navigation. Form memiliki label, inline validation, focus visible dan error summary bila perlu.

## Component contract
Button: default/hover/focus/disabled/loading; loading mencegah duplicate submit. Input: label, helper, error, required, keyboard. Table: sort/filter/pagination, empty/error, accessible row action. Dialog: focus trap, escape, return focus; destructive confirmation. Toast bukan satu-satunya bukti transaksi. AI panel: source, limitations, regenerate, copy, approve; tidak mengubah data tanpa action eksplisit. Publish status per channel, demo badge jelas.

## Integration
Astryx meta/astryx dan Univer dream-num/univer adalah pilihan arah; verify React compatibility, actual token API, license dan commercial boundaries. Jangan mengarang import atau CLI command. Spike satu button, form, table, theme toggle dan workbook; uji build dan keyboard. Fabric.js kandidat editor, bukan mandatory. QA: contrast WCAG 2.2 AA target, keyboard, focus, screen reader, zoom, mobile, dark/custom theme, loading/error/empty. Catat hasil aktual dan screenshot jika tersedia.
