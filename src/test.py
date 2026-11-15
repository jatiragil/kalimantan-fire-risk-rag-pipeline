import pymupdf
doc = pymupdf.open("data/raw_docs/2023sopbmkg024.pdf")
print(doc.to_markdown()[:1000])