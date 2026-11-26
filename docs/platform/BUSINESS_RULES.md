# Financial dan operational contract kandidat
Sumber utama: docs/discovery/reference-cases/bakso-business/PRD.md bagian 6–10. Makna formula asli dipertahankan; penerapan lintas industri berikut merupakan proposal.

## Invariants
Purchase stok menambah inventory asset dan mengurangi cash hanya bila dibayar. Sale mengakui revenue sesuai kebijakan recognition yang disepakati; penerimaan kas dicatat terpisah. Production mengonsumsi bahan dan menghasilkan finished stock; COGS saat finished item terjual, bukan saat bahan dibeli. Untuk made-to-order, consumption dan sale dapat satu transaksi tanpa double count. Waste mengurangi stok dan memiliki cost; jangan menghitung waste dua kali sebagai HPP dan expense. Adjustment membutuhkan reason dan audit. Physical FEFO berbeda dari valuation FIFO/weighted average; LIFO hanya managerial comparison sampai kebijakan reporting diverifikasi.

## Formula dan contoh uji
| ID | Formula | Contoh / expected |
|---|---|---|
| F01 | Unit cost = total cost / units | 200000 / 500 = 400 |
| F02 | Weighted average = sum(q*c)/sum(q) | 120*300 + 100*350 + 80*400 = 103000; /300 = 343.333… |
| F03 | Product HPP = sum(consumed qty*cost)+variable production cost | 3*400 + 2*500 + 800 = 3000 (ilustrasi) |
| F04 | Revenue = qty sold * selling price | 63*5000 = 315000 |
| F05 | Gross profit = revenue - sold HPP | 315000-174500=140500 |
| F06 | Net profit simplified = gross profit - operating cost | 140500-38000=102500 |
| F07 | Markup = (price-cost)/cost | cost 3000 price 4200 = 40% |
| F08 | Margin = profit/revenue | 1200/4200 = 28.571…% |
| F09 | CM = price-variable cost | 5000-3000=2000 |
| F10 | BEP units = ceil(fixed cost/CM) | 43000/2000 → 22; CM<=0 no finite BEP |
| F11 | Target qty = ceil((fixed+target profit)/CM) | (43000+17000)/2000=30 |
| F12 | Cash flow = cash in - cash out | 100000-200000=-100000, bukan otomatis rugi |
| F13 | Ending stock = opening+in-used-waste±adjustment | 100+20-30-5=85 |
| F14 | Waste value = qty*applicable cost | 10*450=4500 |
| F15 | MA = sum(last k observations)/k | 50,60,70 → 60 |
| F16 | WMA = sum(w*d), sum(w)=1 | .2*50+.3*60+.5*70=63 |
| F17 | Absolute error = abs(actual-forecast) | 55 vs 60 → 5 |
| F18 | Safety stock = forecast*safety percentage | 60*10%=6; suggested production 66 |
| F19 | Excess=max(production-demand,0); shortage=max(demand-production,0) | 65 vs 60 → excess 5; 55 vs 60 → shortage 5 |

## Edge cases
Zero quantity denominator: validation error atau metric unavailable, bukan 0 diam-diam. Negative stock: reject default, override policy OPEN. Partial batch issue: alokasikan sesuai valuation policy dan simpan cost snapshot. Refund: reversal revenue dan cash sesuai kejadian; restock hanya bila barang kembali usable. Discount mengurangi revenue sesuai allocation policy. Service cost: material consumed + attributable labor + variable overhead; biaya tetap tidak dihitung dua kali. Booking bukan revenue otomatis; deposit adalah cash event dengan recognition policy OPEN. Multi-product BEP memerlukan sales mix; jangan gunakan formula satu produk tanpa asumsi mix. Rounding residual harus direkonsiliasi, bukan hilang. Tax, statutory accounting, credit sales dan multi-currency memerlukan kebijakan terpisah sebelum implementasi.

## Acceptance
Test purchase tanpa sale tidak menghasilkan COGS; sale setelah production mengurangi finished stock saja; reversal tidak menghapus original; cross-tenant access ditolak; replay request tidak menggandakan ledger; report dapat drill-down ke input; forecast tidak menulis actual. Formula F01–F19 adalah kandidat test vector, bukan hasil test yang sudah dijalankan.
