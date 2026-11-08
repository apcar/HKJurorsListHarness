# Why this harness exists

## The question before the code

This grew out of the Apcar family research: tracking people, occupations, and addresses across years. The Hong Kong Jurors Lists offered a recurring record of those details. A person might change employer, move address, appear under a variant spelling, or disappear from a later list. Each change could be a lead; none, by itself, proves an identity or a life event.

I also wanted to see whether it could be done. Could current AI turn a long series of historical lists into structured, inspectable evidence without quietly rewriting the source—and without spending more on checking the work than on producing it?

The useful end product is not just a searchable name. It is an entry tied to its year, page, and source image, with literal text kept separate from any normalized search form. That would let a researcher follow a lead and return to the evidence. These are selected administrative lists, not a census of everyone who lived in Hong Kong.

## The work that came before

Gwulo’s volunteer Jurors Lists project made this material accessible long before this experiment. Reading its account of the work, and the choices and limitations discussed by its contributors, helped make the scale of the problem concrete for me.

Its early discussion explicitly raised the tension between exact transcription and standardized names and abbreviations; one stated convention excluded accents and umlauts. Later guidance encouraged consistent company names and formatting. Those choices matter when comparing a searchable research resource with a diplomatic transcription that preserves literal detail.

We found source/reference discrepancies, including omissions and conflated entries. But a difference in punctuation or normalization is not automatically a mistake under someone else’s editorial policy. The lesson was to read the scan first, then use Gwulo as a cross-check—not as the starting text or an infallible answer key.

## What the pages actually contain

The inspected lists are printed tables. Columns and wrapped lines carry structure; leader dots, abbreviations, accents, and small marks carry opportunities for error. Some archival witnesses also contain handwriting: an inspected 1854 witness has a handwritten page annotation. That is different from saying the entries themselves are handwritten.

The 1940 acceptance exercise concerns these structured printed lists. It does not establish a general handwriting-recognition capability. A crop can be perfectly readable and still assign an address to the wrong name if the row boundaries are wrong.

## The models did not fail in the same way

Flash made the first large-scale reading economical. It also made some text more conventional than the source. In selected checks, unusual printed names and words became familiar spellings. When a reference transcription made the same change, agreement concealed the problem.

Qwen provided another reading, while Pro served as an informed tiebreaker in the earlier workflow. That distinction matters: a model shown the competing answers is adjudicating, not contributing another blind witness.

A cheap Haiku reread found disagreements, but also introduced them. It expanded Ld. to Ltd. and altered punctuation. A checker could be wrong in precisely the category we needed it to protect. Our earlier comparison and audit rules compounded the problem by ignoring some marks.

Sonnet with a stricter prompt retained more literal detail on a selected hard-case comparison. It still added or dropped punctuation and sometimes treated leader dots as text. That was a useful result for choosing a route, not a universal model ranking: model and prompt changed together, and the comparison was neither a representative sample nor independent human ground truth.

The orchestration failed too. A Gemini benchmark continued issuing requests after credits were exhausted: the corrected record contains 243 billing errors among 246 calls. That tells us nothing about the blocked model’s reading quality. It tells us the workflow needed a global billing stop.

## Before the custom harness

An early Docling test on three printed pages failed the selected 18-record structure check despite reporting successful conversion: columns were concatenated, addresses detached, or people combined. Later geometry-based reconstruction improved the result. Conversion success was not record correctness.

A one-page 1908 local screening test tried standalone PaddleOCR-VL through MLX and a community 4-bit olmOCR conversion. After correcting olmOCR’s input resolution, it produced 59 candidate rows against 56 reference records. Source inspection found an address assigned to the wrong person and wrapped names split into additional rows. These are observations about specific configurations, not rankings of the full projects or their current releases.

A project-configured OpenClaw workflow produced a useful 942-row supplemental 1908 package and resolved its own 53-field hold queue. Reconciling that package with accepted production still required source checks because their identifiers and queues differed. Some intermediate receipts lacked render hashes or usage totals. The lesson was to enforce this task’s controls explicitly, not to declare general-purpose agents useless.

## What changed in the system

The resulting harness gives models narrow jobs. Two readers see the source independently. Strict comparison retains punctuation and accents. Unresolved fields form one deduplicated queue. A single informed adjudication can choose either reading, neither, or leave uncertainty. Gwulo enters afterward as a reference flag.

Python controls the sequence, spending limits, and stopping rules. Every completed compatible request can be reused. Changes to the image, candidates, prompt context, or material settings must invalidate stale results. An interruption must not turn a paid call into an invisible cost or silently repeat it.

This is a custom harness with model orchestration. It is not an autonomous agent society, and adding more agents is not the goal. The purpose is a reliable path from source to a result someone can inspect.

## The first real-evidence milestone

The 1940 acceptance exercise migrated 3,505 pilot entries without changing the retained edition: 3,058 settled, 84 corrected, and 363 uncertain. It preserved 10,988 historical reading variants and 497 informed decisions. All 95 original holds were accounted for. The 33 Special entries on page 1 remain excluded, so this is not a complete-year edition.

Five deliberately chosen real-source cases exercised comparisons, decisions, and release construction using retained evidence. An interrupted import resumed cleanly. Both releases reproduced byte-for-byte with network access refused. That exercise made no new paid transcription calls; the earlier readings and the development work were not free.

The accepted harness had 58 passing offline tests. Publication preparation exposed a history-scanner defect, reproduced it with a failing test, and corrected it. The code draft now passes 59 offline tests.

## The limits are part of the result

This proves migration and mechanics on retained real evidence, not perfect transcription. The review is model-based, with no independent human labels. Full original request settings are missing for 6,547 imported reading variants. The remaining gap inventory contains 363 uncertain entries and 925 resting on weaker evidence.

I directed the research question, source standards, workflow, acceptance criteria, and iteration. AI coding and review agents helped implement, test, and challenge the software. The development history retains that assistance and the repairs. My interest is in whether the system earns trust under inspection.

Earlier local research produced a 962-entry 1906 edition with seven held fields and a 942-entry 1908 edition with 39 held fields. Those used other workflows. The next harness test is a second real year, using the 1939 readings. Broader layout transfer and independently measured accuracy remain work to do. This is a build in public, with a working artifact and visible limits.

## Acknowledgments and sources

Thanks to David Bellis and the contributors to Gwulo’s Jurors Lists project, and to HKU Libraries for access to the historical source material. Gwulo is a reference cross-check; its transcription is not redistributed here. No partnership or endorsement is implied.

- [Gwulo: why the project began and its early transcription discussion](https://gwulo.com/node/6687)
- [Gwulo: typing and formatting guidelines](https://gwulo.com/node/6912)
- [Gwulo: Jurors Lists project](https://gwulo.com/forum/1075)
- [HKU: 1854 source manifest](https://digitalrepository.lib.hku.hk/service/api/iiif/manifest/k930km08c)
- [HKU: 1940 source manifest](https://digitalrepository.lib.hku.hk/service/api/iiif/manifest/m326ss83b)
