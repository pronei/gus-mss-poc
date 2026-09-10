| pair | commit | authors | upgraded | checker (projection) | rules | wire | semantic | outside the per-edge model | agreement |
|---|---|---|---|---|---|---|---|---|---|
| 01-02 | `0cf418d` recommender now returns ids instead of products | unlabelled | recommendation | YES | - | 1 | 0 | - | MISS: wire break, projection passes |
| 02-03 | `2316e25` change Product.id to string | unlabelled | productcatalog | NO | prim-mismatch | 4 | 0 | - | agree: break |
| 03-04 | `22f6fcc` pb: breaking change to currencyservice protos | breaking | currency | YES | - | 1 | 2 | - | MISS: wire break, projection passes |
| 04-05 | `e20ed32` pb: breaking change to Money, remove MoneyAmount | breaking | checkout currency email payment productcatalog shipping | YES | - | 10 | 4 | - | MISS: wire break, projection passes |
| 05-06 | `6f10ac9` breaking changes to Address in proto | breaking | checkout email shipping | YES | - | 0 | 18 | - | agree on wire; semantic-only change both miss |
| 06-07 | `ed942a9` checkoutservice: remove PrepareOrder rpc | unlabelled | checkout | YES | - | 1 | 0 | frontend->checkout CreateOrder: endpoint REMOVED at 07-ed942a9 (/hipstershop.CheckoutServi | agree via endpoint channel |
| 07-08 | `24aaa3e` Add proto for Ads Service. | unlabelled | - | YES | - | 0 | 0 | frontend->ad GetAds: endpoint ADDED at 08-24aaa3e (/hipstershop.AdsService/GetAds); servic | agree: no wire break |
| 08-09 | `390e489` pb: fix style issue in Ads message | unlabelled | ad | YES | - | 0 | 0 | - | agree: no wire break |
| 09-10 | `f35fdbc` Initial commit for Ads Service. (#21) | unlabelled | ad | YES | - | 1 | 2 | frontend->ad GetAds: endpoint path CHANGED /hipstershop.AdsService/GetAds -> /hipstershop. | agree via endpoint channel |
| 10-11 | `86c8c06` pb: add "categories" field to Product (#60) | unlabelled | productcatalog | YES | - | 0 | 0 | - | agree: no wire break |
| 11-12 | `c4d8670` Add licenses (#367) | no-op | - | YES | - | 0 | 0 | - | agree: no wire break |
| 12-13 | `d2c729d` Update Product List to Match Cymbal Branding/Sto | no-op | - | YES | - | 0 | 0 | - | agree: no wire break |
| 13-14 | `76571f5` Clean up docs and meta files (#1721) | no-op | - | YES | - | 0 | 0 | - | agree: no wire break |
| 14-15 | `ca90f35` Bump dependencies in Go services (#2716) | no-op | - | YES | - | 0 | 0 | - | agree: no wire break |

Agreement tally: MISS: wire break, projection passes: 3; agree on wire; semantic-only change both miss: 1; agree via endpoint channel: 2; agree: break: 1; agree: no wire break: 7
