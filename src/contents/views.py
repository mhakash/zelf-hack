import logging
from datetime import timedelta

from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from contents.models import Author, Content, ContentTag, Tag
from contents.serializers import ContentPostSerializer, ContentSerializer

logger = logging.getLogger(__name__)


class CustomPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "items_per_page"
    page_query_param = "page"
    max_page_size = 100


class ContentAPIView(APIView):
    def _build_filters(self, queryset, request):
        query_params = request.query_params.dict()
        author_id = query_params.get("author_id", None)
        author_username = query_params.get("author_username", None)
        timeframe = query_params.get("timeframe", None)
        tag_id = query_params.get("tag_id", None)
        title = query_params.get("title", None)

        if author_id:
            queryset = queryset.filter(author_id=author_id)
        if author_username:
            queryset = queryset.filter(author__username=author_username)
        if timeframe:
            queryset = queryset.filter(timestamp__gte=timezone.now() - timedelta(days=int(timeframe)))
        if tag_id:
            queryset = queryset.filter(contentag__tag_id=tag_id)
        if title:
            queryset = queryset.filter(title__icontains=title)

        return queryset

    def _insert_additional_data_point(self, serialized):
        for serialized_data in serialized.data:
            # Calculating `Total Engagement`
            # Calculating `Engagement Rate`
            view_count = serialized_data["content"]["view_count"]
            total_engagement = (
                serialized_data["content"]["like_count"]
                + serialized_data["content"]["comment_count"]
                + serialized_data["content"]["share_count"]
            )
            if view_count > 0:
                engagement_rate = total_engagement / view_count
            else:
                engagement_rate = 0
            serialized_data["content"]["engagement_rate"] = engagement_rate
            serialized_data["content"]["total_engagement"] = total_engagement
            tags = list(
                ContentTag.objects.filter(content_id=serialized_data["content"]["id"]).values_list(
                    "tag__name", flat=True
                )
            )
            serialized_data["content"]["tags"] = tags

    def get(self, request):
        """
        TODO: Client is complaining about the app performance, the app is loading very slowly, our QA identified that
         this api is slow af. Make the api performant. Need to add pagination. But cannot use rest framework view set.
         As frontend, app team already using this api, do not change the api schema.
         Need to send some additional data as well,
         --------------------------------
         1. Total Engagement = like_count + comment_count + share_count
         2. Engagement Rate = Total Engagement / Views
         Users are complaining these additional data is wrong.
         Need filter support for client side. Add filters for (author_id, author_username, timeframe )
         For timeframe, the content's timestamp must be withing 'x' days.
         Example: api_url?timeframe=7, will get contents that has timestamp now - '7' days
         --------------------------------
         So things to do:
         1. Make the api performant
         2. Fix the additional data point in the schema
            - Total Engagement = like_count + comment_count + share_count
            - Engagement Rate = Total Engagement / Views
            - Tags: List of tags connected with the content
         3. Filter Support for client side
            - author_id: Author's db id
            - author_username: Author's username
            - timeframe: Content that has timestamp: now - 'x' days
            - tag_id: Tag ID
            - title (insensitive match IE: SQL `ilike %text%`)
         4. Must not change the inner api schema
         5. Remove metadata and secret value from schema
         6. Add pagination
            - Should have page number pagination
            - Should have items per page support in query params
            Example: `api_url?items_per_page=10&page=2`
        """
        # query_params = request.query_params.dict()

        queryset = Content.objects.select_related("author")
        queryset = self._build_filters(queryset, request)

        paginator = CustomPagination()
        paginated_content = paginator.paginate_queryset(queryset, request)

        content_data = [{"content": query, "author": query.author} for query in paginated_content]

        serialized = ContentSerializer(content_data, many=True)
        self._insert_additional_data_point(serialized)

        return Response(serialized.data, status=status.HTTP_200_OK)

    def _get_or_create_author(self, author):
        try:
            author_object = Author.objects.get(unique_id=author["unique_external_id"])
        except Author.DoesNotExist:
            Author.objects.create(
                username=author["unique_name"],
                name=author["full_name"],
                unique_id=author["unique_external_id"],
                url=author["url"],
                title=author["title"],
                big_metadata=author["big_metadata"],
                secret_value=author["secret_value"],
            )
            author_object = Author.objects.get(unique_id=author["unique_external_id"])
        return author_object

    def _get_or_create_content(self, content, author_object):
        try:
            content_object = Content.objects.get(unique_id=content["unq_external_id"])
        except Content.DoesNotExist:
            Content.objects.create(
                author=author_object,
                unique_id=content["unq_external_id"],
                url=content["url"],
                title=content["title"],
                like_count=content["stats"]["likes"],
                comment_count=content["stats"]["comments"],
                view_count=content["stats"]["views"],
                share_count=content["stats"]["shares"],
                thumbnail_url=content["thumbnail_url"],
                timestamp=timezone.now(),
                big_metadata=content["big_metadata"],
                secret_value=content["secret_value"],
            )
            content_object = Content.objects.get(unique_id=content["unq_external_id"])
        return content_object

    def _update_tags_mapping(self, tags, content_object):
        for tag in tags:
            try:
                tag_object = Tag.objects.get(name=tag)
                logger.info(f"Tag object: {tag_object}")
            except Tag.DoesNotExist:
                Tag.objects.create(name=tag)
                tag_object = Tag.objects.get(name=tag)
            try:
                content_tag_object = ContentTag.objects.get(tag=tag_object, content=content_object)
                logger.info(f"Content Tag object: {content_tag_object}")

            except ContentTag.DoesNotExist:
                ContentTag.objects.create(tag=tag_object, content=content_object)

    def post(
        self,
        request,
    ):
        """
        TODO: This api is very hard to read, and inefficient.
         The users complaining that the contents they are seeing is not being updated.
         Please find out, why the stats are not being updated.
         ------------------
         Things to change:
         1. This api is hard to read, not developer friendly
         2. Support list, make this api accept list of objects and save it
         3. Fix the users complain
        """

        serializer = ContentPostSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        author = serializer.validated_data.get("author")

        author_object = self._get_or_create_author(author)

        content = serializer.validated_data
        content_object = self._get_or_create_content(content, author_object)
        print(content_object)

        hashtags = serializer.validated_data.get("hashtags")
        self._update_tags_mapping(hashtags, content_object)

        return Response(
            ContentSerializer(
                {
                    "content": content_object,
                    "author": content_object.author,
                }
            ).data,
        )


class ContentStatsAPIView(APIView):
    """
    TODO: This api is taking way too much time to resolve.
     Contents that will be fetched using `ContentAPIView`, we need stats for that
     So it must have the same filters as `ContentAPIView`
     Filter Support for client side
            - author_id: Author's db id
            - author_username: Author's username
            - timeframe: Content that has timestamp: now - 'x' days
            - tag_id: Tag ID
            - title (insensitive match IE: SQL `ilike %text%`)
     -------------------------
     Things To do:
     1. Make the api performant
     2. Fix the additional data point (IE: total engagement, total engagement rate)
     3. Filter Support for client side
         - author_id: Author's db id
         - author_id: Author's db id
         - author_username: Author's username
         - timeframe: Content that has timestamp: now - 'x' days
         - tag_id: Tag ID
         - title (insensitive match IE: SQL `ilike %text%`)
     --------------------------
     Bonus: What changes do we need if we want timezone support?
    """

    def get(self, request):
        query_params = request.query_params.dict()
        tag = query_params.get("tag", None)

        filters = {}
        if tag:
            filters["contentag__tag__name"] = tag

        queryset = Content.objects.filter(**filters).select_related("author")

        data = queryset.aggregate(
            total_likes=Sum("like_count"),
            total_shares=Sum("share_count"),
            total_views=Sum("view_count"),
            total_comments=Sum("comment_count"),
            total_followers=Sum("author__followers"),
            total_contents=Count("id"),
        )

        data["total_engagement"] = data["total_likes"] + data["total_shares"] + data["total_comments"]
        data["total_engagement_rate"] = data["total_engagement"] / data["total_views"] if data["total_views"] else 0

        return Response(data, status=status.HTTP_200_OK)
