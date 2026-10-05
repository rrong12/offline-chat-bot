# Trivia credits

The trivia questions in `trivia.json` come from [Open Trivia DB](https://opentdb.com/), licensed
under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), downloaded on 2026-10-05
with `scripts/fetch_trivia.py`. `?help trivia` names the source and license in chat.

Changes made to the original questions:

- Text was decoded from the API's URL encoding, with invisible characters removed and spaces tidied.
- Easy questions keep their four options. Medium and hard questions are asked without options
  (typed answers), and were kept only if the answer can reasonably be typed.
- Questions were left out if they contained blocked words or mature topics, needed their options to
  make sense, duplicated another question, or were found to be wrong or out of date.

The adapted question bank is shared under the same license.
