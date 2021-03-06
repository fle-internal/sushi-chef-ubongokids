#!/usr/bin/env python

import os
import logging
import json

import youtube_dl

from cache import Db
from youtube import Client, CachingClient

from le_utils.constants import content_kinds, licenses
from ricecooker.chefs import JsonTreeChef
from ricecooker.classes.licenses import get_license
from ricecooker.utils.caching import CacheForeverHeuristic, FileCache, CacheControlAdapter, InvalidatingCacheControlAdapter
from ricecooker.utils.html import download_file
from ricecooker.utils.jsontrees import write_tree_to_json_tree
from ricecooker.utils.zip import create_predictable_zip
from ricecooker.classes.nodes import HTML5AppNode, AudioNode

def create_logger():
    logging.getLogger("cachecontrol.controller").setLevel(logging.WARNING)
    logging.getLogger("requests.packages").setLevel(logging.WARNING)
    from ricecooker.config import LOGGER
    LOGGER.setLevel(logging.DEBUG)
    return LOGGER

class UbongoKidsChef(JsonTreeChef):
    HOSTNAME = 'ubongokids.com'
    ROOT_URL = 'http://www.{}'.format(HOSTNAME)
    DATA_DIR = 'chefdata'
    TREES_DATA_DIR = os.path.join(DATA_DIR, 'trees')
    CRAWLING_STAGE_OUTPUT = 'web_resource_tree.json'
    SCRAPING_STAGE_OUTPUT = 'ricecooker_json_tree.json'
    LICENSE = get_license(licenses.CC_BY_NC_ND, copyright_holder="Ubongo Media").as_dict()
    YOUTUBE_CHANNEL_IDS=['UCwYh0qBAF8HyKt0KUMp1rNg', 'UCjsrL7gPn-S5SJJcKp-OYUA', 'UCcJywQx_THCEr5-1mJbGL9w', 'UC0TLvo891eEEM6HGC5ON7ug']

    def __init__(self, logger, youtube_client_builder_func):
        super(UbongoKidsChef, self).__init__()
        self.logger = logger
        self.youtube_client_factory_func = youtube_client_builder_func
        self.youtube_client_dispose_func = None
        self.youtube = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.youtube_client_dispose_func:
            self.youtube_client_dispose_func()

    def pre_run(self, args, options):
        self.youtube, self.youtube_client_dispose_func = self.youtube_client_factory_func(options.get('caching', False))
        self.crawl(args, options)
        self.scrape(args, options)

    def crawl(self, args, options):
        web_resource_tree = dict(
            kind='UbongoKidsWebResourceTree',
            title='Ubongo Kids is a Tanzanian edutainment cartoon made by Ubongo Media.',
            children=[self.crawl_youtube_channel(cid) for cid in UbongoKidsChef.YOUTUBE_CHANNEL_IDS]
        )
        with open(os.path.join(UbongoKidsChef.TREES_DATA_DIR, UbongoKidsChef.CRAWLING_STAGE_OUTPUT), 'w') as f:
            json.dump(web_resource_tree, f, indent=2)
            self.logger.info('Crawling results stored')
        return web_resource_tree

    def crawl_youtube_channel(self, channel_id):
        youtube_channel = self.youtube.get_channel_data(channel_id)
        title = youtube_channel['name']
        return dict(
            kind='UbongoKidsYoutubeChannel',
            id=youtube_channel['id'],
            title=title,
            url=youtube_channel['url'],
            children=[self.crawl_youtube_playlist(playlist_id) for playlist_id in youtube_channel['playlists']],
            language=youtube_channel.get('language', 'en'),
        )

    def crawl_youtube_playlist(self, playlist_id):
        playlist = self.youtube.get_playlist_data(playlist_id)
        title = playlist['name']
        return dict(
            kind='UbongoKidsYoutubePlaylist',
            id=playlist['id'],
            title=title,
            url=playlist['url'],
            children=[self.crawl_youtube_video(video_id) for video_id in playlist['videos']],
            language=playlist.get('language', 'en'),
        )

    def crawl_youtube_video(self, video_id):
        video = self.youtube.get_video_data(video_id)
        result = dict(kind='UbongoKidsYoutubeVideo', language=video.get('language', 'en'))
        result.update(video)
        return result

    def scrape(self, args, options):
        with open(os.path.join(UbongoKidsChef.TREES_DATA_DIR, UbongoKidsChef.CRAWLING_STAGE_OUTPUT), 'r') as f:
            web_resource_tree = json.load(f)
            assert web_resource_tree['kind'] == 'UbongoKidsWebResourceTree'

        ricecooker_json_tree = dict(
            source_domain=UbongoKidsChef.HOSTNAME,
            source_id='ubongokids',
            title='UbongoKids',
            description="""Ubongo is a Tanzanian social enterprise that creates fun, localized edutainment for learners in Africa. "Ubongo" means brain in Kiswahili, and we're all about finding fun ways to stimulate kids (and kids at heart) to use their brains. Our entertaining media help learners understand concepts, rather than memorizing them. And we use catchy songs and captivating imagery to make sure they never forget!"""[:400],
            thumbnail='http://www.ubongokids.com/wp-content/uploads/2016/06/logo_ubongo_kids-150x100.png',
            language='en',
            children=[self.scrape_youtube_channel(child) for child in web_resource_tree['children']],
            # TODO:
            license=UbongoKidsChef.LICENSE,
        )
        write_tree_to_json_tree(os.path.join(UbongoKidsChef.TREES_DATA_DIR, UbongoKidsChef.SCRAPING_STAGE_OUTPUT), ricecooker_json_tree)
        return ricecooker_json_tree

    def scrape_youtube_channel(self, channel):
        return dict(
            kind=content_kinds.TOPIC,
            source_id=channel['id'],
            title=channel['title'],
            description='',
            children=[self.scrape_youtube_playlist(playlist) for playlist in channel['children']],
            language=channel['language'],
            # TODO
            license=UbongoKidsChef.LICENSE,
        )

    def scrape_youtube_playlist(self, playlist):
        return dict(
            kind=content_kinds.TOPIC,
            source_id=playlist['id'],
            title=playlist['title'],
            children=[self.scrape_youtube_video(video) for video in playlist['children']],
            language=playlist['language'],
            # TODO
            license=UbongoKidsChef.LICENSE,
        )

    def scrape_youtube_video(self, video):
        return dict(
            kind=content_kinds.VIDEO,
            source_id=video['id'],
            title=video['title'],
            thumbnail=video['thumbnail'],
            description=video['description'],
            files=[dict(file_type=content_kinds.VIDEO, youtube_id=video['id'])],
            language=video['language'],
            # TODO
            license=UbongoKidsChef.LICENSE,
        )

if __name__ == '__main__':
    def build_youtube_client(use_caching):
        yt = Client(youtube_dl.YoutubeDL(dict(verbose=True, no_warnings=True, writesubtitles=True, allsubtitles=True)))
        if use_caching:
            cache = Db(os.path.join(os.getcwd(), '.cache'), 'ubongokids').__enter__()
            return CachingClient(yt, cache), lambda: cache.__exit__()
        return yt, None

    with UbongoKidsChef(create_logger(), build_youtube_client) as chef:
        chef.main()
