import re
import sys

import xml.etree.ElementTree as ETree

from pathlib import Path

from urllib import request
from urllib.error import HTTPError

import pandas as pd
import tqdm


NAMESPACES = {
            "dc": "http://purl.org/dc/elements/1.1/",
            "dcterms" : "http://purl.org/dc/terms/",
            "olac" : "http://www.language-archives.org/OLAC/1.1/",
            "xsi" : "http://www.w3.org/2001/XMLSchema-instance",
            "oai" : "http://www.openarchives.org/OAI/2.0/",
            "doi" : "http://datacite.org/schema/kernel-4",
            "crdo" : "http://cocoon.huma-num.fr/schemas/",

        }

def extract_records(metadata):

    def extract_doi(xml):

        for identifiant in xml.findall('.//dc:identifier', NAMESPACES):
            if "doi:" in identifiant.text:
                return identifiant.text.replace('doi:','')

    def parse_length(length):

        if length is None:
            return None
        
        length_regexp = re.compile(r"PT((?P<hours>[0-9]*)H)?((?P<minutes>[0-9]*)M)?((?P<seconds>[0-9]*)S)?")
        if result_regex_min := length_regexp.search(length.text):
            hours = int(result_regex_min.group("hours")) if result_regex_min.group("hours") is not None else 0
            minutes = int(result_regex_min.group("minutes")) if result_regex_min.group("minutes") is not None else 0
            seconds = int(result_regex_min.group("seconds")) if result_regex_min.group("seconds") is not None else 0
            return hours * 3_600 + minutes * 60 + seconds
        
        assert False, f"{length.text} can not be parsed"

    def extract_uri(xml):

        for el in xml_record.findall('.//dc:identifier', NAMESPACES):
            if el.text.split(".")[-1] == "xml":
                return el.text

        for el in xml_record.findall('.//dcterms:isFormatOf', NAMESPACES):
            if el.text.split(".")[-1] == "wav":
                return el.text

        return None

    def first(el):
        if el is None or not el:
            return None
        
        return el[0].text

    tree = ETree.parse(metadata)
    root = tree.getroot()

    all_records = []
    for xml_record in tqdm.tqdm(root.findall(".//oai:record", NAMESPACES)):
        if (accessRights := xml_record.find(".//dcterms:accessRights", NAMESPACES)) is not None:
            if accessRights.text != "Freely accessible":
                continue

        # ignore collections 
        # better way : check that "xsi:type" attribuet of dc:subject is "olac:language"
        if not xml_record.findall('.//dc:subject', NAMESPACES) or not xml_record.findall('.//dc:subject', NAMESPACES)[0].text:
            continue

        #assert len(xml_record.findall('.//dc:subject', NAMESPACES)) == 1

        #print(extract_uri(xml_record))
        #if extract_doi(xml_record) != "10.24397/PANGLOSS-0000868":
        #    continue

        record = {
            "oai": xml_record.find("*/oai:identifier", NAMESPACES).text,
            "datestamp": xml_record.find('*/oai:datestamp', NAMESPACES).text,    # regarder la date de l'enregistrement balise created de l'audio
            "language": xml_record.findall('.//dc:subject', NAMESPACES)[0].text,
            "doi": extract_doi(xml_record),
            "length": parse_length(xml_record.find(".//dcterms:extent", NAMESPACES)),
            "uri": extract_uri(xml_record),
            "requires": first(xml_record.findall('.//dcterms:requires', NAMESPACES)),
        }

        #print(record)
        all_records.append(record)

    return pd.DataFrame(all_records)


def lazzy_download(url, dest):
        
    if not dest.is_file():
        try:
            request.urlretrieve(url, dest)
        except HTTPError:
            print ("erreur")


def download_annotated_data(row, corpus_dir):

    dest_dir = corpus_dir / row["language"]

    dest_dir.mkdir(exist_ok=True, parents=True)

    lazzy_download(row["uri_audios"], dest_dir / (row["doi"].split("/")[1] + ".wav"))
    lazzy_download(row["uri_annotations"], dest_dir / (row["doi"].split("/")[1] + ".xml"))


if __name__ == "__main__":

    import argparse
    import logging

    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", required=True)
    parser.add_argument("--languages", nargs="+",
                        help="keeps only records in the languages listed")
    parser.add_argument("--corpus_dir", default=Path("corpus"), type=Path)
    args = parser.parse_args()

    args.languages = set(args.languages)

    records = extract_records(args.metadata)
    records.to_csv("records.csv")

    if (errors := args.languages.difference(records["language"].unique())):
        sys.exit(f"the the metadata '{args.metadata}' do not contain any records in the following languages: {errors}")

    logging.info("filtering languages")
    records = records[records["language"].isin(args.languages) & ~records["uri"].isna()]

    annotations = records[records["uri"].str.endswith("xml")]
    audios = records[records["uri"].str.endswith("wav")]

    audios_with_annotations = pd.merge(audios, annotations[["uri", "requires"]],
                                       right_on="requires",
                                       left_on="oai",
                                       suffixes=("_audios", '_annotations'),
                                       validate="1:1",
                                       how="left")

    audios_with_annotations = audios_with_annotations[["oai", "datestamp", "language", "doi", "length", "uri_audios", "uri_annotations"]]
    audios_with_annotations.apply(lambda row: download_annotated_data(row, args.corpus_dir), axis=1)
