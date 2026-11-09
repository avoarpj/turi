import nltk

def setup_nltk():
    resources = [
        ('stemmers/rslp', 'rslp'),
        ('corpora/stopwords', 'stopwords')
    ]
    
    for path, name in resources:
        try:
            nltk.data.find(path)
        except LookupError:
            print(f"Downloading NLTK resource: {name}")
            nltk.download(name, quiet=True)