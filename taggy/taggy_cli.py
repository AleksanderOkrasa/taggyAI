"""
A console (CLI) version of our image-tagging and duplicates-grouping tool.
Uses 'click' to parse commands and flags from the command line.

Usage examples:
  # 1. Group duplicates with advanced best-image selection
  python taggy_cli.py duplicates --images-path ./images --output-folder ./output --similarity-threshold 0.9

  # 2. Tag images
  python taggy_cli.py tag --images-path ./images --threshold 0.3 --top-k 5

  # 3. Search images by text
  python taggy_cli.py search --images-path ./images --query "cat" --top-k 3
"""

import os
import click

from utils.file_utils import (
    load_config, save_metadata_to_json,
    list_supported_image_files,
    )
from utils.logger import get_logger
from utils.image_tagger import ImageTagger

logger = get_logger(__name__)

@click.group()
@click.option('--config-file', '-c', default='taggy/config.ini', help='Path to the config file.')
@click.pass_context
def cli(ctx, config_file):
    """
    Main entry point for the Taggy CLI.
    """
    ctx.ensure_object(dict)
    defaults = load_config(config_file)
    ctx.obj['defaults'] = defaults
    
    labels_from_config = defaults.get("labels", "random, general").split(',')
    labels = [label.strip() for label in labels_from_config]
    ctx.obj['labels'] = labels
    
    face_cascade_path = defaults.get("face_cascade_path", None)
    ctx.obj['face_cascade_path'] = face_cascade_path
    
    
@cli.command("duplicates")
@click.option("--images-path", "-i", type=click.Path(exists=True), required=True,
              help="Path to the folder containing images.")
@click.option("--output-folder", "-o", type=click.Path(),
              help="Folder to place grouped duplicates.")
@click.option("--labels", "-l",  multiple=True,
              help="List of labels used for grouping names of duplicates (if not provided, uses default).")
@click.option('--operation', '-op', type=click.Choice(['copy', 'symlink', 'move']),
              help='File operation(s) to perform when grouping duplicates.')
@click.option("--similarity-threshold", "-t", default=0.9, type=float,
              help="Threshold (0..1) for considering images duplicates.")
@click.option("--face-cascade", type=click.Path(exists=False), default=None,
              help="Path to the Haar cascade XML file for face detection.")
@click.option("--propose-best", "-b", is_flag=True,
              help="If provided, proposes 'best' images to keep in each group.")
@click.option("--best-method", type=click.Choice(["advanced", "laplacian"]), default="advanced",
              help="How to score 'best' images.")
@click.pass_context
def find_duplicates_cmd(ctx, images_path, output_folder, labels, operation, similarity_threshold, face_cascade, propose_best, best_method):
    """
    Finds and groups duplicate images based on their embedding similarity.
    Then organizes them into subfolders, picking 'best images' if desired.
    """
    defaults = ctx.obj['defaults']
    if not operation:
        operation = defaults.get("operation", "symlink")
    if not labels:
        labels = ctx.obj['labels']
    if not face_cascade:
        face_cascade = ctx.obj['face_cascade_path']
        
    click.echo(f"Operation: {operation}, Labels: {labels}")
    click.echo(f"Finding duplicates in {images_path} with threshold={similarity_threshold} ...")

    tagger = ImageTagger(model_name="CLIP", face_cascade_path=face_cascade, labels=labels)

    duplicates = tagger.find_duplicates(images_path, similarity_threshold=similarity_threshold)
    if not duplicates:
        click.echo("No duplicates found.")
        return
    logger.info(f"Found {len(duplicates)} duplicate groups.")

    all_images = list_supported_image_files(images_path)
    output_folder=  output_folder if output_folder else f"{images_path}/taggy_output/duplicates/"
    tagger.group_duplicates(
        duplicates=duplicates,
        output_folder= output_folder,
        operation=operation,
        propose_best=propose_best,
        all_images=all_images if operation in ["copy", "symlink"] else None,
        best_scoring_method=best_method,
    )

    logger.info("Done grouping duplicates.")


@cli.command("tag")
@click.option("--images-path", "-i", type=click.Path(exists=True), required=True,
              help="Path to the folder containing images.")
@click.option("--threshold", "-t", type=float, default=0.3,
              help="Minimum probability threshold for assigning a label.")
@click.option("--top-k", "-k", type=int, default=5,
              help="Number of top tags to return.")
@click.option("--labels", "-l",  multiple=True,
              help="List of labels used for tagging (if not provided, uses default).")
@click.option("--one-output-json", type=click.Path(), default=None,
              help="If provided, saves tags per every file to one provided JSON file.")
@click.option("--operation", "-op", type=click.Choice(['copy', 'symlink']),
                default="symlink",  help="File operation to perform. Grouped by detected labels, "
                                         "working with --output-folder parameter. Default is 'symlink'.")
@click.option("--images-output-folder", "-o", type=click.Path(),
              help="Folder to place tagged images. When you want to do some operation on files what was found."
                   "Graphics may be repeated (one image can be in many folders).")
@click.option("--create-many-output-jsons", "-j", is_flag=True,
              help="If provided, saves tags per every file to separate JSON files.")
@click.pass_context
def tag_images_cmd(ctx, images_path, threshold, top_k, labels, operation,
                   one_output_json, create_many_output_jsons, images_output_folder):
    """
    Assigns labels to each image in images_path using the CLIP model.
    """
    defaults = ctx.obj['defaults']
    if not operation:
        operation = defaults.get("operation", "symlink")
    if not labels:
        labels = ctx.obj['labels']
    
    click.echo(f"Operation: {operation}, Labels: {labels}")
    click.echo(f"Tagging images in {images_path} with threshold={threshold}, top_k={top_k}.")
    tagger = ImageTagger(model_name="CLIP", labels=labels)


    image_files = list_supported_image_files(images_path)
    if not image_files:
        click.echo("No images found in the given folder.")
        return
    logger.info(f"Found {len(image_files)} images.")

    results_list = []
    count_images = len(image_files)-1
    for i, file_path in enumerate(image_files):
        tags_scored = tagger.tag_image(
            file_path,
            output_path=f"{file_path}.json" if create_many_output_jsons else None,
            top_k=top_k,
            labels=labels,
            threshold=threshold,
            operation=operation,
            output_folder=images_output_folder,
        )
        results_list.append({
            "file": file_path,
            "tags": tags_scored
        })
        click.echo(f"#{i}/{count_images} Tagged {os.path.basename(file_path)} => {[x['tag'] for x in tags_scored]}")

    if one_output_json and results_list:
        save_metadata_to_json(results_list, one_output_json)
        click.echo(f"Saved tagging results to {one_output_json}.")
    logger.info("Done tagging images.")
    if images_output_folder:
        logger.info(f"Images saved [operation: {operation}] to {images_output_folder} grouped by tags (images may be repeated)")
    
    
@cli.command("search")
@click.option("--images-path", "-i", type=click.Path(exists=True), required=True,
              help="Path to the folder containing images.")
@click.option("--query", "-q", type=str, required=True,
              help="Text query for searching similar images.")
@click.option("--output-folder", "-o", type=click.Path(),
              help="Folder to place search results. Use if you want to do some operation on files what was found.")
@click.option("--operation", "-op", type=click.Choice(['copy', 'symlink', 'move']),
              default="copy", help="File operation to perform when searching images. Default is 'copy'")
@click.option("--top-k", "-k", type=int, default=5,
              help="Number of top results to return.")
def search_images_cmd(images_path, query, top_k, output_folder, operation):
    """
    Searches for images most similar to the provided text query using CLIP embeddings.
    """
    click.echo(f"Searching images in {images_path} for query='{query}'...")
    tagger = ImageTagger(model_name="CLIP")

    results = tagger.search_images(query, images_path, top_k=top_k, output_path=output_folder, operation=operation)
    if not results:
        click.echo("No results found (no images or none matched).")
        return

    click.echo(f"Top {top_k} results for '{query}':")
    for i, (img_path, score) in enumerate(results):
        click.echo(f"{i+1}. {img_path} => similarity={score:.4f}")


if __name__ == "__main__":
    cli()
