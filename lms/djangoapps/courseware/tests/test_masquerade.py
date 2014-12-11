"""
Unit tests for masquerade.
"""
import json
from mock import patch
from datetime import datetime
from django.utils.timezone import UTC

from django.core.urlresolvers import reverse
from django.test.utils import override_settings

from capa.tests.response_xml_factory import OptionResponseXMLFactory
from courseware.tests.factories import StaffFactory
from student.tests.factories import UserFactory
from courseware.tests.helpers import LoginEnrollmentTestCase
from xmodule.modulestore.tests.django_utils import ModuleStoreTestCase, TEST_DATA_MOCK_MODULESTORE
from xmodule.modulestore.tests.factories import ItemFactory, CourseFactory


@override_settings(MODULESTORE=TEST_DATA_MOCK_MODULESTORE)
class MasqueradeTestCase(ModuleStoreTestCase, LoginEnrollmentTestCase):
    """
    Base class for masquerade tests that sets up a test course and enrolls a user in the course.
    """
    def setUp(self):
        # By default, tests run with DISABLE_START_DATES=True. To test that masquerading as a student is
        # working properly, we must use start dates and set a start date in the past (otherwise the access
        # checks exist prematurely).
        self.course = CourseFactory.create(number='masquerade-test', metadata={'start': datetime.now(UTC())})
        self.chapter = ItemFactory.create(
            parent_location=self.course.location,
            category="chapter",
            display_name="Test Section",
        )
        self.sequential_display_name = "Test Masquerade Subsection"
        self.sequential = ItemFactory.create(
            parent_location=self.chapter.location,
            category="sequential",
            display_name=self.sequential_display_name,
        )
        self.vertical = ItemFactory.create(
            parent_location=self.sequential.location,
            category="vertical",
            display_name="Test Unit",
        )
        problem_xml = OptionResponseXMLFactory().build_xml(
            question_text='The correct answer is Correct',
            num_inputs=2,
            weight=2,
            options=['Correct', 'Incorrect'],
            correct_option='Correct'
        )
        self.problem_display_name = "Test Masquerade Problem"
        self.problem = ItemFactory.create(
            parent_location=self.vertical.location,
            category='problem',
            data=problem_xml,
            display_name=self.problem_display_name
        )
        self.test_user = self.create_test_user()
        self.login(self.test_user.email, 'test')
        self.enroll(self.course, True)

    def get_courseware_page(self):
        """
        Returns the HTML rendering for the courseware page.
        """
        url = reverse(
            'courseware_section',
            kwargs={
                'course_id': unicode(self.course.id),
                'chapter': self.chapter.location.name,
                'section': self.sequential.location.name,
            }
        )
        return self.client.get(url)

    def verify_staff_debug_present(self, staff_debug_expected):
        """
        Verifies that the staff debug control visibility is as expected (for staff only).
        """
        content = self.get_courseware_page().content
        self.assertTrue(self.sequential_display_name in content, "Subsection should be visible")
        self.assertEqual(staff_debug_expected, 'Staff Debug Info' in content)

    def get_problem(self):
        """
        Returns the JSON content for the problem in the course.
        """
        problem_url = reverse(
            'xblock_handler',
            kwargs={
                'course_id': unicode(self.course.id),
                'usage_id': unicode(self.problem.location),
                'handler': 'xmodule_handler',
                'suffix': 'problem_get'
            }
        )
        return self.client.get(problem_url)

    def verify_show_answer_present(self, show_answer_expected):
        """
        Verifies that "Show Answer" is only present when expected (for staff only).
        """
        problem_html = json.loads(self.get_problem().content)['html']
        self.assertTrue(self.problem_display_name in problem_html)
        self.assertEqual(show_answer_expected, "Show Answer" in problem_html)


class NormalStudentVisibilityTest(MasqueradeTestCase):
    """
    Verify the course displays as expected for a "normal" student (to ensure test setup is correct).
    """
    def create_test_user(self):
        """
        Creates a normal student user.
        """
        return UserFactory()

    @patch.dict('django.conf.settings.FEATURES', {'DISABLE_START_DATES': False})
    def test_staff_debug_not_visible(self):
        """
        Tests that staff debug control is not present for a student.
        """
        self.verify_staff_debug_present(False)

    @patch.dict('django.conf.settings.FEATURES', {'DISABLE_START_DATES': False})
    def test_show_answer_not_visible(self):
        """
        Tests that "Show Answer" is not visible for a student.
        """
        self.verify_show_answer_present(False)


class TestStaffMasqueradeAsStudent(MasqueradeTestCase):
    """
    Check for staff being able to masquerade as student.
    """
    def create_test_user(self):
        """
        Creates a staff user.
        """
        return StaffFactory(course_key=self.course.id)

    def update_masquerade(self, role, group_id=None):
        """
        Toggle masquerade state.
        """
        masquerade_url = reverse(
            'masquerade_update',
            kwargs={
                'course_key_string': unicode(self.course.id),
            }
        )
        response = self.client.post(
            masquerade_url,
            json.dumps({"role": role, "group_id": group_id}),
            "application/json"
        )
        self.assertEqual(response.status_code, 204)
        return response

    @patch.dict('django.conf.settings.FEATURES', {'DISABLE_START_DATES': False})
    def test_staff_debug_with_masquerade(self):
        """
        Tests that staff debug control is not visible when masquerading as a student.
        """
        # Verify staff initially can see staff debug
        self.verify_staff_debug_present(True)

        # Toggle masquerade to student
        self.update_masquerade(role='student')
        self.verify_staff_debug_present(False)

        # Toggle masquerade back to staff
        self.update_masquerade(role='staff')
        self.verify_staff_debug_present(True)

    @patch.dict('django.conf.settings.FEATURES', {'DISABLE_START_DATES': False})
    def test_show_answer_for_staff(self):
        """
        Tests that "Show Answer" is not visible when masquerading as a student.
        """
        # Verify that staff initially can see "Show Answer".
        self.verify_show_answer_present(True)

         # Toggle masquerade to student
        self.update_masquerade(role='student')
        self.verify_show_answer_present(False)

        # Toggle masquerade back to staff
        self.update_masquerade(role='staff')
        self.verify_show_answer_present(True)
