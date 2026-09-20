<script setup>
import EnrollmentForm from './EnrollmentForm.vue';
import EnrolledPersonsList from './EnrolledPersonsList.vue';
</script>

<template>
  <div class="grid gap-3 md:grid-cols-2">
    <EnrollmentForm />
    <EnrolledPersonsList />
  </div>
</template>
