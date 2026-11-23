from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from apps.audit.middleware import RequestIDMiddleware


class RequestIDMiddlewareTests(SimpleTestCase):
    def test_request_id_is_generated_and_returned(self):
        middleware = RequestIDMiddleware(lambda request: HttpResponse("ok"))
        request = RequestFactory().get("/", HTTP_X_REQUEST_ID="untrusted")

        response = middleware(request)

        self.assertEqual(len(request.request_id), 32)
        self.assertEqual(response["X-Request-ID"], request.request_id)
        self.assertNotEqual(response["X-Request-ID"], "untrusted")
