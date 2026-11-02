# SuperChat: routing test log

**Command:** `python eval_routing.py` (add `-v` to print every reply)
**Data:** official mock dataset. Reference date: Monday, 2 November 2026.
**Test set:** 45 scripted conversations with 119 user turns, in English, Azerbaijani (at least 13 turns) and Russian (at least 11 turns). Every conversation starts from a fresh session and freshly loaded data. The test set includes the 8 sample conversations from section 7 of the brief. The longest conversation switches domain 5 times.

Each turn is checked twice:
1. **Routing:** the category the router picks must equal the expected category.
2. **Answer:** the reply must contain an expected fact, such as the right flight number, price, total or clarifying question. This catches cases where the routing is right but the answer is wrong.

## Results

| Metric | Result |
|---|---|
| Routing accuracy | **119 / 119 = 100.0 %** |
| Answer checks | **110 / 110 = 100.0 %** |

| Category | Correct / total |
|---|---|
| flights | 21 / 21 |
| shopping | 22 / 22 |
| cinema | 25 / 25 |
| mixed | 4 / 4 |
| follow_up | 31 / 31 |
| ambiguous | 6 / 6 |
| out_of_scope | 8 / 8 |
| greeting / small talk | 2 / 2 |

## Error analysis

The final score comes after fixing the errors that the test set found during development. Earlier runs scored 44/45, then 87/92, then 107/111 (routing) and 96/98 (answers). These were the errors, grouped by cause:

1. **Missing vocabulary (routing).** Colour words were not shopping keywords, so "Mavi olan hansıdır?" went to out of scope. "Only morning ones" and "Sort by fewest stops" had no follow-up signal. *Fix:* added colours, time-of-day words and sort/compare verbs to the keyword lists.
2. **Entity extraction (answers).**
   - "Round trip … on 6 November, return on 9 November" lost the outbound date, because the text was split at the first "round trip" marker instead of at "return".
   - "Add 2 board games" ignored the quantity.
   - "between 50 and 100 AZN" was not read as a price range.
   *Fix:* split only at return markers, read a bare digit as the quantity in cart commands, and added range patterns in EN, AZ and RU.
3. **Unknown places produced misleading answers.** "Flights to Paris on Friday" reused the previous route. This would break the "never invent" rule. *Fix:* a place after "to/from/в/из" that is not in the route network now gets an explicit "no flights for 'paris'" with the list of available destinations.
4. **Booking intent lost across turns.** After "Which showtime should I book?", the reply "the first one" showed details instead of booking. With both a flight and a film on the table, "Book it" went to whichever domain was used last. *Fix:* a pending booking request is kept until the user names the item. When two domains could be booked, the system asks "flight or cinema tickets?".
5. **Wrong expectations in the test itself (3 cases).** For example, "Add it to my cart" was labelled `shopping` but is correctly a `follow_up`. The reply was right; the label was corrected.

## Known weak spots (not covered by a 100 % score)

- The router is rule-based. A phrasing whose words are not in the keyword lists, for example a product described only by a synonym we did not add, falls to `out_of_scope` or `ambiguous`. A larger, independently written test set would probably score lower than 100 %.
- Azerbaijani suffix handling is heuristic: case endings on city names (Bakı**dan**, İstanbul**a**) and word stems.
- Two intents of the same domain in one message (two different flights) are handled as one search.
